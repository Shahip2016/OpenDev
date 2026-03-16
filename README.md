# OpenDev: AI Software Engineering Agent

OpenDev is a terminal-native, autonomous software engineering agent implemented according to the "Building AI Coding Agents for the Terminal" paper framework.

## Architecture

This compound AI system operates through a structured four-layer architecture:

1. **Entry & UI**: Command-line interface with `prompt-toolkit` and Rich formatting
2. **Agent Layer**: Main agent and Subagent orchestrator via single-entry Factory
3. **Tool & Context**: Extended ReAct execution loop, Context Engineering, Tool schema registry
4. **Persistence & Safety**: 4-tier configuration, Session JSONL serialization, Defense-in-depth safety

## Features

- **Extended ReAct Loop**: 4-phase iteration cycle with doom-loop detection (Algorithm 1)
- **Context Engineering**: Staged compaction, Reminder system, ACE memory, Prompt composer
- **Safety Architecture**: Multi-level execution modes (AUTO/SEMI/PLAN), strict tool approval, single-step Undo
- **Tool Registry**: 21+ tools spanning Files, Processes, Web, and LSP-driven AST search
- **Subagent System**: 8 specialized capability-filtered subagents (Code-Explorer, Planner, etc.)
- **Two-phase Skills**: Discover and invoke instructional resources on-the-fly

## CLI Usage

Run OpenDev using the `opendev` console script with optional arguments (Table 5):

```bash
# Start in semi-auto mode (default)
opendev

# Run entirely autonomous without approvals
opendev --mode auto

# Run in read-only planning mode
opendev --mode plan

# Force high-depth thinking and Reflection
opendev --thinking high

# Resume a previous session
opendev --resume a1b2c3d4
```

## Configuration

Settings cascade through 4 tiers: Defaults → User-Global → Env Vars → Project-Local (`.opendev/config.yaml`).

Store your API keys safely as environment variables:
```bash
export OPENDEV_OPENAI_API_KEY="sk-..."
export OPENDEV_ANTHROPIC_API_KEY="sk-ant-..."
```
