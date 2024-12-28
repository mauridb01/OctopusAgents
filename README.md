# OctopusAgents: AI Agent Framework

[![Twitter Follow](https://img.shields.io/twitter/follow/OctopusAgentFW?style=social)](https://twitter.com/OctopusAgentFW)

CA:

OctopusAgents is a library developed using Fetch.ai that allows for creating autonomous twitter agent in Python. With simple and expressive decorators, you can have an agent that performs various tasks on a schedule or takes action on various events.

## ⚡ Quickstart

### Installation

Get started with OctopusAgents by installing it for Python 3.9 to 3.12:

    pip install OctopusAgents

### Running a Demo

#### Creating an Agent

Build your first OctopusAgent using the following script:

```python3
from OctopusAgents import Agent, Context
alice = Agent(name="alice", seed="alice recovery phrase")
```

Include a seed parameter when creating an agent to set fixed addresses, or leave it out to generate a new random address each time.

#### Giving it a task

Give it a simple task, such as a greeting:

```python3
@alice.on_interval(period=2.0)
async def say_hello(ctx: Context):
    ctx.logger.info(f'hello, my name is {ctx.agent.name}')

if __name__ == "__main__":
    alice.run()
```

#### Running the Agent

So far, your code should look like this:

```python3
from OctopusAgents import Agent, Context

alice = Agent(name="alice", seed="alice recovery phrase")

@alice.on_interval(period=2.0)
async def say_hello(ctx: Context):
    ctx.logger.info(f'hello, my name is {ctx.agent.name}')

if __name__ == "__main__":
    alice.run()
```

Run it using:

```bash
python agent.py
```

You should see the results in your terminal.

## 📖 Documentation

Please see the [official documentation](https://fetch.ai/docs) for full setup instructions and advanced features.

- [👋 Introduction](https://fetch.ai/docs/concepts/agents/agents)
- [💻 Installation](https://fetch.ai/docs/guides/agents/installing-OctopusAgent)
- Tutorials
  - [🤖 Create an agent](https://fetch.ai/docs/guides/agents/create-a-OctopusAgent)
  - [🛣️ Agent Communication](https://fetch.ai/docs/guides/agents/communicating-with-other-agents)
  - [🍽️ Restaurant Booking Demo](https://fetch.ai/docs/guides/agents/booking-demo)
- Key Concepts:
  - [📍Addresses](https://fetch.ai/docs/guides/agents/getting-OctopusAgent-address)
  - [💾 Storage](https://fetch.ai/docs/guides/agents/storage-function)
  - [📝 Interval Tasks](https://fetch.ai/docs/guides/agents/interval-task)
  - [🌐 Agent Broadcast](https://fetch.ai/docs/guides/agents/broadcast)
  - [⚙️ Almanac Contracts](https://fetch.ai/docs/guides/agents/register-in-almanac)

## 🌱 Examples

The [`examples`](https://github.com/fetchai/OctopusAgents/tree/main/python/examples) folder contains several examples of how to create and run various types of agents.

## 🌲 Integrations

The [`integrations`](https://github.com/fetchai/OctopusAgents/tree/main/integrations) folder contains examples that provide a more in depth use of the OctopusAgents library.

## Python Library

Go to the [`python`](https://github.com/fetchai/OctopusAgents/tree/main/python) folder for details on the Python OctopusAgents library.

## ✨ Contributing

All contributions are welcome! Remember, contribution includes not only code, but any help with docs or issues raised by other developers. See our [contribution guidelines](https://github.com/fetchai/OctopusAgents/blob/main/CONTRIBUTING.md) for more details.

### 📄 Development Guidelines

Read our [development guidelines](https://github.com/fetchai/OctopusAgents/blob/main/DEVELOPING.md) to learn some useful tips related to development.

### ❓ Issues, Questions, and Discussions

We use [GitHub Issues](https://github.com/fetchai/OctopusAgents/issues) for tracking requests and bugs, and [GitHub Discussions](https://github.com/fetchai/OctopusAgents/discussions) for general questions and discussion.

## 🛡 Disclaimer

This project, OctopusAgents, is provided "as-is" without any warranty, express or implied. By using this software, you agree to assume all risks associated with its use, including but not limited to unexpected behavior, data loss, or any other issues that may arise. The developers and contributors of this project do not accept any responsibility or liability for any losses, damages, or other consequences that may occur as a result of using this software.

## License

The OctopusAgents project is licensed under [Apache License 2.0](https://github.com/fetchai/OctopusAgents/blob/main/LICENSE).
