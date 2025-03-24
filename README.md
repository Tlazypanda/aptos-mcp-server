# Aptos MCP Server

A Model Context Protocol (MCP) server for interacting with Aptos documentation and creating full-stack Aptos blockchain applications.

## Features

- 🔍 Browse and search Aptos documentation
- 🔧 Create new Aptos projects (fullstack, contract, or client)
- 🧩 Generate components for Aptos projects
- 🧪 Test Aptos Move contracts
- 📜 Generate TypeScript ABI interfaces for Move contracts

## Installation

### Prerequisites

- Python 3.10 or later
- Node.js and npm
- Aptos CLI (for some tooling features)

### Setup

1. Install the mcp package:

```bash
uv add "mcp[cli]"
# or 
pip install "mcp[cli]"
```

2. Clone this repository:

```bash
git clone https://github.com/yourusername/aptos-mcp-server.git
cd aptos-mcp-server
```

3. Install dependencies:

```bash
uv add httpx
# or
pip install httpx
```

4. (Optional) Set GitHub token for increased API rate limits:

```bash
export GITHUB_TOKEN=your_github_token
```

## Using with Claude Desktop

1. Install Claude Desktop from [claude.ai/download](https://claude.ai/download)

2. Add the Aptos MCP Server to your Claude Desktop configuration:

```bash
mcp install aptos_mcp_server.py
```

Or manually edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "aptos-dev": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/aptos-mcp-server",
        "run",
        "aptos_mcp_server.py"
      ]
    }
  }
}
```

3. Restart Claude Desktop

## Development

Run the server in development mode with the MCP Inspector:

```bash
mcp dev aptos_mcp_server.py
```

## Usage

Once connected to Claude Desktop, you can:

### Browse Aptos Documentation

Ask Claude to browse through the Aptos documentation repository:

- "Show me the Aptos documentation structure"
- "Find information about Move modules in the Aptos docs"
- "Get me the Table implementation documentation"

### Create New Projects

Ask Claude to set up new Aptos projects:

- "Create a new Aptos full-stack project called 'my-first-dapp'"
- "Generate a Move smart contract for a marketplace"
- "Set up a client-only Aptos project"

### Generate Components

Ask Claude to generate components for your Aptos projects:

- "Generate a React component for connecting to Aptos wallet"
- "Create a Move table for storing user profiles"
- "Make a client function for querying contract data"

### Test and Generate ABIs

Ask Claude to test contracts and generate interfaces:

- "Test my Aptos contract at ~/projects/my-dapp/move"
- "Generate TypeScript bindings for my Move contract"

## Example Queries

- "Browse through the Aptos documentation"
- "Search the Aptos docs for 'table'"
- "Create a new Aptos fullstack project called 'nft-marketplace'"
- "Generate a Move module for a token contract"
- "Create a React component for wallet connection"
- "Generate TypeScript ABI for my contract"
- "Test my contract's withdraw function"

## License

MIT