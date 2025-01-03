import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

import aiohttp
from cosmpy.aerial.client import LedgerClient
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.address import Address
from pydantic import BaseModel

from uagents.config import (
    ALMANAC_API_MAX_RETRIES,
    ALMANAC_API_TIMEOUT_SECONDS,
    ALMANAC_API_URL,
    ALMANAC_CONTRACT_VERSION,
    ALMANAC_REGISTRATION_WAIT,
    REGISTRATION_FEE,
    REGISTRATION_UPDATE_INTERVAL_SECONDS,
)
from uagents.crypto import Identity
from uagents.network import (
    AlmanacContract,
    AlmanacContractRecord,
    InsufficientFundsError,
    add_testnet_funds,
)
from uagents.types import AgentEndpoint, AgentInfo


class VerifiableModel(BaseModel):
    agent_address: str
    signature: Optional[str] = None
    timestamp: Optional[int] = None

    def sign(self, identity: Identity):
        self.timestamp = int(time.time())
        digest = self._build_digest()
        self.signature = identity.sign_digest(digest)

    def verify(self) -> bool:
        return self.signature is not None and Identity.verify_digest(
            self.agent_address, self._build_digest(), self.signature
        )

    def _build_digest(self) -> bytes:
        sha256 = hashlib.sha256()
        sha256.update(
            json.dumps(
                self.model_dump(exclude={"signature"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return sha256.digest()


class AgentRegistrationAttestation(VerifiableModel):
    protocols: List[str]
    endpoints: List[AgentEndpoint]
    metadata: Optional[Dict[str, Union[str, Dict[str, str]]]] = None


class AgentRegistrationAttestationBatch(BaseModel):
    attestations: List[AgentRegistrationAttestation]


class AgentStatusUpdate(VerifiableModel):
    is_active: bool


def generate_backoff_time(retry: int) -> float:
    """
    Generate a backoff time starting from 0.128 seconds and limited to ~131 seconds
    """
    return (2 ** (min(retry, 11) + 6)) / 1000


def coerce_metadata_to_str(
    metadata: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Union[str, Dict[str, str]]]]:
    """
    Step through the metadata and convert any non-string values to strings.
    """
    if metadata is None:
        return None
    out = {}
    for key, val in metadata.items():
        if isinstance(val, dict):
            out[key] = {
                k: v if isinstance(v, str) else json.dumps(v) for k, v in val.items()
            }
        else:
            out[key] = val if isinstance(val, str) else json.dumps(val)
    return out


def extract_geo_metadata(
    metadata: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Extract geo-location metadata from the metadata dictionary.
    """
    if metadata is None:
        return None
    return {k: v for k, v in metadata.items() if k == "geolocation"}


async def almanac_api_post(
    url: str, data: BaseModel, raise_from: bool = True, retries: int = 3
) -> bool:
    async with aiohttp.ClientSession() as session:
        for retry in range(retries):
            try:
                async with session.post(
                    url,
                    headers={"content-type": "application/json"},
                    data=data.model_dump_json(),
                    timeout=aiohttp.ClientTimeout(total=ALMANAC_API_TIMEOUT_SECONDS),
                ) as resp:
                    resp.raise_for_status()
                    return True
            except (aiohttp.ClientError, asyncio.exceptions.TimeoutError) as e:
                if retry == retries - 1:
                    if raise_from:
                        raise e
                    return False
                await asyncio.sleep(generate_backoff_time(retry))
    return False


class AgentRegistrationPolicy(ABC):
    @abstractmethod
    # pylint: disable=unnecessary-pass
    async def register(
        self,
        agent_address: str,
        protocols: List[str],
        endpoints: List[AgentEndpoint],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        pass


class BatchRegistrationPolicy(ABC):
    @abstractmethod
    # pylint: disable=unnecessary-pass
    async def register(self):
        pass

    @abstractmethod
    def add_agent(self, agent_info: AgentInfo, identity: Identity):
        pass


class AlmanacApiRegistrationPolicy(AgentRegistrationPolicy):
    def __init__(
        self,
        identity: Identity,
        *,
        almanac_api: Optional[str] = None,
        max_retries: int = ALMANAC_API_MAX_RETRIES,
        logger: Optional[logging.Logger] = None,
    ):
        self._almanac_api = almanac_api or ALMANAC_API_URL
        self._max_retries = max_retries
        self._identity = identity
        self._logger = logger or logging.getLogger(__name__)

    async def register(
        self,
        agent_address: str,
        protocols: List[str],
        endpoints: List[AgentEndpoint],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        # create the attestation
        attestation = AgentRegistrationAttestation(
            agent_address=agent_address,
            protocols=protocols,
            endpoints=endpoints,
            metadata=coerce_metadata_to_str(extract_geo_metadata(metadata)),
        )

        # sign the attestation
        attestation.sign(self._identity)

        success = await almanac_api_post(
            f"{self._almanac_api}/agents", attestation, retries=self._max_retries
        )
        if success:
            self._logger.info("Registration on Almanac API successful")
        else:
            self._logger.warning("Registration on Almanac API failed")


class BatchAlmanacApiRegistrationPolicy(AgentRegistrationPolicy):
    def __init__(
        self, almanac_api: Optional[str] = None, logger: Optional[logging.Logger] = None
    ):
        self._almanac_api = almanac_api or ALMANAC_API_URL
        self._attestations: List[AgentRegistrationAttestation] = []
        self._logger = logger or logging.getLogger(__name__)

    def add_agent(self, agent_info: AgentInfo, identity: Identity):
        attestation = AgentRegistrationAttestation(
            agent_address=agent_info.agent_address,
            protocols=list(agent_info.protocols),
            endpoints=agent_info.endpoints,
            metadata=coerce_metadata_to_str(extract_geo_metadata(agent_info.metadata)),
        )
        attestation.sign(identity)
        self._attestations.append(attestation)

    async def register(self):
        if not self._attestations:
            return
        attestations = AgentRegistrationAttestationBatch(
            attestations=self._attestations
        )
        success = await almanac_api_post(
            f"{self._almanac_api}/agents/batch", attestations
        )
        if success:
            self._logger.info("Batch registration on Almanac API successful")
        else:
            self._logger.warning("Batch registration on Almanac API failed")


class LedgerBasedRegistrationPolicy(AgentRegistrationPolicy):
    def __init__(
        self,
        identity: Identity,
        ledger: LedgerClient,
        wallet: LocalWallet,
        almanac_contract: AlmanacContract,
        testnet: bool,
        *,
        logger: Optional[logging.Logger] = None,
    ):
        self._identity = identity
        self._wallet = wallet
        self._ledger = ledger
        self._testnet = testnet
        self._almanac_contract = almanac_contract
        self._logger = logger or logging.getLogger(__name__)

    def check_contract_version(self):
        """
        Check the version of the deployed Almanac contract and log a warning
        if it is different from the supported version.
        """
        deployed_version = self._almanac_contract.get_contract_version()
        if deployed_version != ALMANAC_CONTRACT_VERSION:
            self._logger.warning(
                "Mismatch in almanac contract versions: supported (%s), deployed (%s). "
                "Update uAgents to the latest version for compatibility.",
                ALMANAC_CONTRACT_VERSION,
                deployed_version,
            )

    async def register(
        self,
        agent_address: str,
        protocols: List[str],
        endpoints: List[AgentEndpoint],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Register the agent on the Almanac contract if registration is about to expire or
        the registration data has changed.
        """
        self.check_contract_version()

        if (
            not self._almanac_contract.is_registered(agent_address)
            or self._almanac_contract.get_expiry(agent_address)
            < REGISTRATION_UPDATE_INTERVAL_SECONDS
            or endpoints != self._almanac_contract.get_endpoints(agent_address)
            or protocols != self._almanac_contract.get_protocols(agent_address)
        ):
            if self._get_balance() < REGISTRATION_FEE:
                self._logger.warning(
                    "I do not have enough funds to register on Almanac contract"
                )
                if self._testnet:
                    add_testnet_funds(str(self._wallet.address()))
                    self._logger.info(
                        f"Adding testnet funds to {self._wallet.address()}"
                    )
                else:
                    self._logger.info(
                        f"Send funds to wallet address: {self._wallet.address()}"
                    )
                raise InsufficientFundsError()

            self._logger.info("Registering on almanac contract...")

            current_time = int(time.time()) - ALMANAC_REGISTRATION_WAIT

            signature = self._sign_registration(current_time)
            await self._almanac_contract.register(
                self._ledger,
                self._wallet,
                agent_address,
                protocols,
                endpoints,
                signature,
                current_time,
            )
            self._logger.info("Registering on almanac contract...complete")
        else:
            self._logger.info("Almanac contract registration is up to date!")

    def _get_balance(self) -> int:
        return self._ledger.query_bank_balance(Address(self._wallet.address()))

    def _sign_registration(self, timestamp: int) -> str:
        """
        Sign the registration data for Almanac contract.

        Args:
            timestamp (int): The timestamp for the registration.

        Returns:
            str: The signature of the registration data.

        Raises:
            AssertionError: If the Almanac contract address is None.

        """
        assert self._almanac_contract.address is not None
        return self._identity.sign_registration(
            str(self._almanac_contract.address),
            timestamp,
            str(self._wallet.address()),
        )


class BatchLedgerRegistrationPolicy(BatchRegistrationPolicy):
    def __init__(
        self,
        ledger: LedgerClient,
        wallet: LocalWallet,
        almanac_contract: AlmanacContract,
        testnet: bool,
        logger: Optional[logging.Logger] = None,
    ):
        self._ledger = ledger
        self._wallet = wallet
        self._almanac_contract = almanac_contract
        self._testnet = testnet
        self._logger = logger or logging.getLogger(__name__)
        self._records: List[AlmanacContractRecord] = []
        self._identities: Dict[str, Identity] = {}

    def add_agent(self, agent_info: AgentInfo, identity: Identity):
        agent_record = AlmanacContractRecord(
            agent_address=agent_info.agent_address,
            protocols=agent_info.protocols,
            endpoints=agent_info.endpoints,
            contract_address=str(self._almanac_contract.address),
            sender_address=str(self._wallet.address()),
        )
        self._records.append(agent_record)
        self._identities[agent_info.agent_address] = identity

    def _get_balance(self) -> int:
        return self._ledger.query_bank_balance(Address(self._wallet.address()))

    async def register(self):
        self._logger.info("Registering agents on Almanac contract...")
        for record in self._records:
            record.sign(self._identities[record.agent_address])

        if self._get_balance() < REGISTRATION_FEE * len(self._records):
            self._logger.warning(
                f"I do not have enough funds to register {len(self._records)} "
                "agents on Almanac contract"
            )
            if self._testnet:
                add_testnet_funds(str(self._wallet.address()))
                self._logger.info(f"Adding testnet funds to {self._wallet.address()}")
            else:
                self._logger.info(
                    f"Send funds to wallet address: {self._wallet.address()}"
                )
            raise InsufficientFundsError()

        await self._almanac_contract.register_batch(
            self._ledger, self._wallet, self._records
        )

        self._logger.info("Registering agents on Almanac contract...complete")


class DefaultRegistrationPolicy(AgentRegistrationPolicy):
    def __init__(
        self,
        identity: Identity,
        ledger: LedgerClient,
        wallet: LocalWallet,
        almanac_contract: Optional[AlmanacContract],
        testnet: bool,
        *,
        logger: Optional[logging.Logger] = None,
        almanac_api: Optional[str] = None,
    ):
        self._logger = logger or logging.getLogger(__name__)
        self._api_policy = AlmanacApiRegistrationPolicy(
            identity, almanac_api=almanac_api, logger=logger
        )
        if almanac_contract is None:
            self._ledger_policy = None
        else:
            self._ledger_policy = LedgerBasedRegistrationPolicy(
                identity, ledger, wallet, almanac_contract, testnet, logger=logger
            )

    async def register(
        self,
        agent_address: str,
        protocols: List[str],
        endpoints: List[AgentEndpoint],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        # prefer the API registration policy as it is faster
        try:
            await self._api_policy.register(
                agent_address, protocols, endpoints, metadata
            )
        except Exception as e:
            self._logger.warning(
                f"Failed to register on Almanac API: {e.__class__.__name__}"
            )

        if self._ledger_policy is None:
            return

        # schedule the ledger registration
        try:
            await self._ledger_policy.register(
                agent_address, protocols, endpoints, metadata
            )
        except InsufficientFundsError:
            self._logger.warning(
                "Failed to register on Almanac contract due to insufficient funds"
            )
            raise
        except Exception as e:
            self._logger.error(f"Failed to register on Almanac contract: {e}")
            raise


async def update_agent_status(status: AgentStatusUpdate, almanac_api: str):
    await almanac_api_post(
        f"{almanac_api}/agents/{status.agent_address}/status",
        status,
        raise_from=False,
    )


class DefaultBatchRegistrationPolicy(BatchRegistrationPolicy):
    def __init__(
        self,
        ledger: LedgerClient,
        wallet: Optional[LocalWallet] = None,
        almanac_contract: Optional[AlmanacContract] = None,
        testnet: bool = True,
        *,
        logger: Optional[logging.Logger] = None,
        almanac_api: Optional[str] = None,
    ):
        self._logger = logger or logging.getLogger(__name__)
        self._api_policy = BatchAlmanacApiRegistrationPolicy(
            almanac_api=almanac_api, logger=logger
        )

        if almanac_contract is None or wallet is None:
            self._ledger_policy = None
        else:
            self._ledger_policy = BatchLedgerRegistrationPolicy(
                ledger, wallet, almanac_contract, testnet, logger=logger
            )

    def add_agent(self, agent_info: AgentInfo, identity: Identity):
        self._api_policy.add_agent(agent_info, identity)
        if self._ledger_policy is not None:
            self._ledger_policy.add_agent(agent_info, identity)

    async def register(self):
        # prefer the API registration policy as it is faster
        try:
            await self._api_policy.register()
        except Exception as e:
            self._logger.warning(
                f"Failed to batch register on Almanac API: {e.__class__.__name__}"
            )

        if self._ledger_policy is None:
            return

        # schedule the ledger registration
        try:
            await self._ledger_policy.register()
        except InsufficientFundsError:
            self._logger.warning(
                "Failed to batch register on Almanac contract due to insufficient funds"
            )
            raise
        except Exception as e:
            self._logger.error(f"Failed to batch register on Almanac contract: {e}")
            raise
