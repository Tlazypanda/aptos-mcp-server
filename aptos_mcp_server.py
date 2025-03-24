from mcp.server.fastmcp import FastMCP, Context
import os
import httpx
import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass
import tempfile
import subprocess
import shutil
import asyncio
from urllib.parse import urlparse

# Create an MCP server
mcp = FastMCP("AptosDevTools")

# GitHub repo information
APTOS_DOCS_REPO = "aptos-labs/developer-docs"
APTOS_DOCS_RAW_BASE = "https://raw.githubusercontent.com/aptos-labs/developer-docs/main"
APTOS_DOCS_API_BASE = f"https://api.github.com/repos/{APTOS_DOCS_REPO}/contents"
APTOS_DOCS_WEB_BASE = f"https://github.com/{APTOS_DOCS_REPO}/blob/main"

# Local cache for documentation
CACHE_DIR = Path(tempfile.gettempdir()) / "aptos-mcp-cache"
CACHE_DIR.mkdir(exist_ok=True)

@dataclass
class DocFile:
    path: str
    name: str
    type: str
    content: Optional[str] = None

async def fetch_github_content(path: str = "") -> List[DocFile]:
    """Fetch directory contents or file content from GitHub"""
    url = f"{APTOS_DOCS_API_BASE}/{path}" if path else APTOS_DOCS_API_BASE
    
    cache_key = f"github_{path.replace('/', '_')}"
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_data = json.load(f)
            
        # Check if we're dealing with a file or directory listing
        if isinstance(cached_data, list):
            return [DocFile(item["path"], item["name"], item["type"]) for item in cached_data]
        else:
            # Single file with content
            import base64
            content = base64.b64decode(cached_data["content"]).decode("utf-8")
            return [DocFile(cached_data["path"], cached_data["name"], "file", content)]
    
    async with httpx.AsyncClient() as client:
        headers = {}
        if github_token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"token {github_token}"
            
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Cache the response
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        
        if isinstance(data, list):
            # Directory listing
            return [DocFile(item["path"], item["name"], item["type"]) for item in data]
        else:
            # Single file with content
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            return [DocFile(data["path"], data["name"], "file", content)]

async def fetch_file_content(path: str) -> str:
    """Fetch and return file content"""
    files = await fetch_github_content(path)
    if files and files[0].content:
        return files[0].content
    return f"Failed to fetch content for {path}"

def get_file_extension(path: str) -> str:
    """Get the file extension from a path"""
    return Path(path).suffix.lower()

def get_mime_type(path: str) -> str:
    """Determine the MIME type based on file extension"""
    ext = get_file_extension(path)
    mime_types = {
        ".md": "text/markdown",
        ".mdx": "text/markdown",
        ".json": "application/json",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".ts": "text/typescript",
        ".js": "text/javascript",
        ".jsx": "text/javascript",
        ".tsx": "text/typescript",
        ".html": "text/html",
        ".css": "text/css",
        ".move": "text/plain",
        ".txt": "text/plain",
    }
    return mime_types.get(ext, "text/plain")

@mcp.resource("aptos-docs://browse/{path}")
async def browse_docs(path: str = "") -> str:
    """Browse the Aptos documentation repository"""
    try:
        files = await fetch_github_content(path)
        result = []
        
        if path:
            # Add a back link if we're in a subdirectory
            parent_path = str(Path(path).parent)
            if parent_path == ".":
                parent_path = ""
            result.append(f"[../ (Go up)]({APTOS_DOCS_WEB_BASE}/{parent_path})")
        
        # Sort by type (directories first) then by name
        files.sort(key=lambda x: (0 if x.type == "dir" else 1, x.name))
        
        for file in files:
            if file.type == "dir":
                result.append(f"📁 [{file.name}/]({APTOS_DOCS_WEB_BASE}/{file.path})")
            else:
                result.append(f"📄 [{file.name}]({APTOS_DOCS_WEB_BASE}/{file.path})")
        
        return "\n".join(result)
    except Exception as e:
        return f"Error browsing documentation: {str(e)}"

@mcp.resource("aptos-docs://file/{path}")
async def get_doc_file(path: str) -> str:
    """Get the content of a specific documentation file"""
    try:
        content = await fetch_file_content(path)
        return content
    except Exception as e:
        return f"Error retrieving file: {str(e)}"

@mcp.resource("aptos-docs://search/{query}")
async def search_docs(query: str) -> str:
    """Search the Aptos documentation for a specific term"""
    try:
        results = []
        # First, get the file list recursively
        # For this example, we'll just search the top-level md files
        files = await fetch_github_content()
        markdown_files = [file for file in files if file.type == "file" and 
                         (file.name.endswith(".md") or file.name.endswith(".mdx"))]
        
        for file in markdown_files:
            content = await fetch_file_content(file.path)
            if query.lower() in content.lower():
                # Add context by grabbing a snippet around the match
                matches = []
                for i, line in enumerate(content.split('\n')):
                    if query.lower() in line.lower():
                        start = max(0, i - 1)
                        end = min(len(content.split('\n')), i + 2)
                        context = '\n'.join([f"{j+1}: {l}" for j, l in 
                                             enumerate(content.split('\n')[start:end], start)])
                        matches.append(context)
                
                if matches:
                    results.append(f"## [{file.name}]({APTOS_DOCS_WEB_BASE}/{file.path})")
                    for i, match in enumerate(matches[:3]):  # Limit to 3 matches per file
                        results.append(f"Match {i+1}:\n```\n{match}\n```\n")
        
        if not results:
            return f"No results found for '{query}'"
        
        return "\n".join(results)
    except Exception as e:
        return f"Error searching documentation: {str(e)}"

@mcp.tool()
async def create_aptos_project(project_name: str, project_type: str = "fullstack") -> str:
    """
    Create a new Aptos project using the Aptos CLI.
    
    Args:
        project_name: Name of the project
        project_type: Type of project (fullstack, contract, client)
    """
    supported_types = ["fullstack", "contract", "client"]
    if project_type not in supported_types:
        return f"Unsupported project type. Choose from: {', '.join(supported_types)}"
    
    # Command to generate project
    cmd = ["npx", "@aptos-labs/aptos-cli@latest", "init", project_name, "--type", project_type]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully created {project_type} project '{project_name}'.\n\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error creating project: {e.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def generate_aptos_component(component_type: str, component_name: str, 
                                  project_dir: str, options: str = "") -> str:
    """
    Generate a new component for an Aptos project.
    
    Args:
        component_type: Type of component (table, module, etc.)
        component_name: Name of the component
        project_dir: Project directory path
        options: Additional options as a string
    """
    supported_types = ["move-module", "react-component", "client-function", "table"]
    
    if component_type not in supported_types:
        return f"Unsupported component type. Choose from: {', '.join(supported_types)}"
    
    project_dir = os.path.expanduser(project_dir)  # Expand ~ in paths
    
    if not os.path.exists(project_dir):
        return f"Project directory not found: {project_dir}"
    
    try:
        # Different command logic based on component type
        if component_type == "move-module":
            module_code = generate_move_module(component_name)
            module_path = os.path.join(project_dir, "move", "sources", f"{component_name}.move")
            os.makedirs(os.path.dirname(module_path), exist_ok=True)
            
            with open(module_path, "w") as f:
                f.write(module_code)
            
            return f"Generated Move module at {module_path}"
            
        elif component_type == "react-component":
            component_code = generate_react_component(component_name, options)
            component_path = os.path.join(project_dir, "client", "src", "components", 
                                        f"{component_name}.tsx")
            os.makedirs(os.path.dirname(component_path), exist_ok=True)
            
            with open(component_path, "w") as f:
                f.write(component_code)
            
            return f"Generated React component at {component_path}"
            
        elif component_type == "client-function":
            function_code = generate_client_function(component_name, options)
            function_path = os.path.join(project_dir, "client", "src", "utils", 
                                       f"{component_name}.ts")
            os.makedirs(os.path.dirname(function_path), exist_ok=True)
            
            with open(function_path, "w") as f:
                f.write(function_code)
            
            return f"Generated client function at {function_path}"
            
        elif component_type == "table":
            table_code = generate_move_table(component_name, options)
            table_path = os.path.join(project_dir, "move", "sources", f"{component_name}_table.move")
            os.makedirs(os.path.dirname(table_path), exist_ok=True)
            
            with open(table_path, "w") as f:
                f.write(table_code)
            
            return f"Generated Move table at {table_path}"
        
        return f"Unknown component type: {component_type}"
    
    except Exception as e:
        return f"Error generating component: {str(e)}"

def generate_gas_station_server() -> str:
    """Generate the server code for a gas station"""
    return """import express, { Request, Response } from 'express';
import {
    Account, AccountAuthenticator,
    Aptos,
    AptosConfig,
    Deserializer,
    Network,
    NetworkToNetworkName,
    SimpleTransaction,
} from '@aptos-labs/ts-sdk';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
app.use(express.json());

const PORT = process.env.PORT ? parseInt(process.env.PORT) : 3000;

const APTOS_NETWORK = NetworkToNetworkName[process.env.APTOS_NETWORK || ''] || Network.DEVNET;

const config = new AptosConfig({network: APTOS_NETWORK});
const aptos = new Aptos(config);

const feePayerAccount = Account.generate();
console.log(`Gas Station Account Address: ${feePayerAccount.accountAddress.toString()}`);

// Fund the feePayerAccount account
const fundFeePayerAccount = async () => {
    console.log('=== Funding Gas Station Account ===');
    try {
        await aptos.fundAccount({
            accountAddress: feePayerAccount.accountAddress,
            amount: 100_000_000,
        });
        console.log('Gas Station Account funded successfully.');
    } catch (error) {
        console.error('Error funding Gas Station Account:', error);
        console.log('Note: Automatic funding only works on DEVNET. On other networks, manually fund this address.');
    }
};

app.post('/signAndSubmit', async (req: Request, res: Response) => {
    try {
        const {transactionBytes, senderAuthenticator} = req.body;

        if (!transactionBytes) {
            return res.status(400).json({error: 'transactionBytes is required'});
        }
        if (!senderAuthenticator) {
            return res.status(400).json({error: 'senderAuthenticator is required'});
        }

        console.log('=== Received Transaction Request ===');

        // Deserialize the raw transaction
        const deserializer = new Deserializer(Uint8Array.from(transactionBytes));
        const transaction = SimpleTransaction.deserialize(deserializer);

        console.log('=== Signing Transaction as Fee Payer ===');

        // Gas station signs the transaction as fee payer
        const feePayerAuthenticator = aptos.transaction.signAsFeePayer({
            signer: feePayerAccount,
            transaction,
        });

        const deserializedSenderAuth = AccountAuthenticator.deserialize(new Deserializer(Uint8Array.from(senderAuthenticator)));

        console.log('=== Submitting Sponsored Transaction ===');
        const signedTxnInput = {
            transaction,
            senderAuthenticator: deserializedSenderAuth,
            feePayerAuthenticator,
        };
        let response = await aptos.transaction.submit.simple(signedTxnInput);
        
        console.log(`Transaction submitted. Hash: ${response.hash}`);
        await aptos.waitForTransaction({transactionHash: response.hash});
        console.log('Transaction executed successfully!');

        return res.status(200).json({
            transactionHash: response.hash,
            message: 'Transaction sponsored and executed successfully',
            feePayerAddress: feePayerAccount.accountAddress.toString()
        });
    } catch (error) {
        console.error('Error processing transaction:', error);
        return res.status(500).json({error: String(error)});
    }
});

// Health check endpoint
app.get('/health', (req: Request, res: Response) => {
    return res.status(200).json({
        status: 'healthy',
        network: APTOS_NETWORK,
        feePayerAddress: feePayerAccount.accountAddress.toString()
    });
});

app.listen(PORT, async () => {
    console.log(`Gas Station Server running on http://localhost:${PORT}`);
    if (process.env.AUTO_FUND_ACCOUNT === 'true') {
        await fundFeePayerAccount();
    }
});
"""

def generate_gas_station_client() -> str:
    """Generate the client code for a gas station"""
    return """import axios from 'axios';
import { Account, Aptos, AptosConfig, Network, } from '@aptos-labs/ts-sdk';

const GAS_STATION_URL = "http://localhost:3000";

const main = async () => {
    const config = new AptosConfig({ network: Network.DEVNET });
    const aptos = new Aptos(config);

    console.log("=== Aptos Gas Station Client Demo ===");
    
    // Create sender and recipient accounts
    const alice = Account.generate();
    const bob = Account.generate();

    console.log("Alice's address:", alice.accountAddress.toString());
    console.log("Bob's address:", bob.accountAddress.toString());

    // Fund Alice's account (the transaction sender, but not fee payer)
    console.log("\\n=== Funding Alice's account ===");
    await aptos.fundAccount({ accountAddress: alice.accountAddress, amount: 100_000_000 });
    console.log("Alice's account funded");

    // Build a transaction (Alice sending APT to Bob)
    console.log("\\n=== Building transaction ===");
    const transaction = await aptos.transaction.build.simple({
        sender: alice.accountAddress,
        withFeePayer: true,  // Important: Mark that this transaction will have a fee payer
        data: {
            function: "0x1::aptos_account::transfer",
            functionArguments: [bob.accountAddress, 100],  // Sending 100 octas to Bob
        },
    });
    
    console.log("Transaction built successfully");

    // Alice signs the transaction (but doesn't pay for gas)
    console.log("\\n=== Alice signing transaction ===");
    const senderAuthenticator = aptos.transaction.sign({ signer: alice, transaction });
    console.log("Transaction signed by Alice");

    // Send the transaction to the gas station for fee sponsorship
    console.log("\\n=== Sending to Gas Station for sponsorship ===");
    try {
        const response = await axios.post(
            `${GAS_STATION_URL}/signAndSubmit`,
            {
                transactionBytes: Array.from(transaction.bcsToBytes()),
                senderAuthenticator: Array.from(senderAuthenticator.bcsToBytes()),
            },
            {
                headers: {
                    "Content-Type": "application/json",
                },
            }
        );

        const { transactionHash, feePayerAddress } = response.data;

        console.log("Transaction sponsored by:", feePayerAddress);
        console.log("Transaction submitted. Hash:", transactionHash);
        
        // Wait for transaction to be executed
        console.log("\\n=== Waiting for transaction execution ===");
        const executedTx = await aptos.waitForTransaction({ transactionHash });
        console.log("Transaction executed successfully!");
        
        // Verify Bob received the funds
        console.log("\\n=== Checking Bob's balance ===");
        const bobBalance = await aptos.getAccountAPTAmount({ accountAddress: bob.accountAddress });
        console.log("Bob's balance:", bobBalance, "octas");
        
    } catch (error) {
        console.error("Error:", error.response?.data || error.message);
    }
};

main();
"""

def generate_transaction_processor(project_name: str) -> str:
    """Generate code for a transaction processor"""
    return f"""import {{
  InputModels,
  Models,
  OutputModels,
  ProcessingResult,
  Transaction,
  TransactionModel,
  TransactionProcessor,
  UserTransactionInput,
  parseTransaction,
}} from "@aptos-labs/indexer-sdk";

/**
 * {project_name.capitalize()} Transaction Processor
 * 
 * This processor handles transactions and extracts relevant information.
 */
export class {project_name.capitalize()}TransactionProcessor extends TransactionProcessor {{
  constructor() {{
    super();
  }}

  /**
   * Process a batch of transactions
   */
  async process(
    transactionInputs: UserTransactionInput[],
  ): Promise<ProcessingResult> {{
    const processingResult = new ProcessingResult();
    console.log(`Processing ${{transactionInputs.length}} transactions`);

    for (const transactionInput of transactionInputs) {{
      const transaction = parseTransaction(transactionInput);
      
      // Process each transaction
      try {{
        await this.processTransaction(transaction, processingResult);
      }} catch (e) {{
        console.error(
          `Error processing transaction ${{transaction.version}}: ${{e}}`,
        );
      }}
    }}

    return processingResult;
  }}

  /**
   * Process a single transaction
   */
  async processTransaction(
    transaction: Transaction,
    processingResult: ProcessingResult,
  ): Promise<void> {{
    // Check if transaction is successful
    if (!transaction.success) {{
      return;
    }}

    // Extract basic transaction data
    const txModel = new TransactionModel();
    txModel.version = transaction.version;
    txModel.hash = transaction.hash;
    txModel.sender = transaction.sender;
    txModel.success = transaction.success;
    txModel.timestamp = new Date(Number(transaction.timestamp) / 1000);
    txModel.blockHeight = transaction.blockHeight;
    
    // Add to processing result
    processingResult.transactionModel = txModel;

    // Process specific entry functions
    if (transaction.payload?.type === "entry_function_payload") {{
      const entryFunctionFullStr = transaction.payload.function;
      
      // Example: Process a specific entry function
      if (entryFunctionFullStr === "0x1::coin::transfer") {{
        // Handle coin transfer function
        this.processCoinTransfer(transaction, processingResult);
      }}
      
      // TODO: Add more function handlers
    }}
  }}

  /**
   * Process a coin transfer transaction
   */
  private processCoinTransfer(
    transaction: Transaction,
    processingResult: ProcessingResult,
  ): void {{
    if (
      transaction.payload?.type !== "entry_function_payload" ||
      !transaction.payload.arguments
    ) {{
      return;
    }}

    try {{
      // Extract function arguments
      const [recipient, amount] = transaction.payload.arguments;
      
      // Create custom transaction model
      const transferModel = new Models.{project_name.capitalize()}TransferModel();
      transferModel.version = transaction.version;
      transferModel.sender = transaction.sender;
      transferModel.recipient = recipient as string;
      transferModel.amount = BigInt(amount as string);
      transferModel.timestamp = new Date(Number(transaction.timestamp) / 1000);
      
      // Add to processing result
      processingResult.models.push(transferModel);
      
      console.log(
        `Processed transfer: ${{transaction.sender}} -> ${{recipient}} (${{amount}})`,
      );
    }} catch (e) {{
      console.error(`Error processing coin transfer: ${{e}}`);
    }}
  }}
}}

// Register processor
new {project_name.capitalize()}TransactionProcessor().start();
"""

def generate_event_processor(project_name: str) -> str:
    """Generate code for an event processor"""
    return f"""import {{
  InputModels,
  Models,
  OutputModels,
  ProcessingResult,
  Event,
  EventProcessor,
  UserTransactionInput,
  parseEvent,
}} from "@aptos-labs/indexer-sdk";

/**
 * {project_name.capitalize()} Event Processor
 * 
 * This processor handles events and extracts relevant information.
 */
export class {project_name.capitalize()}EventProcessor extends EventProcessor {{
  constructor() {{
    super();
  }}

  /**
   * Process a batch of events
   */
  async process(
    eventInputs: InputModels.Event[],
  ): Promise<ProcessingResult> {{
    const processingResult = new ProcessingResult();
    console.log(`Processing ${{eventInputs.length}} events`);

    for (const eventInput of eventInputs) {{
      const event = parseEvent(eventInput);
      
      // Process each event
      try {{
        await this.processEvent(event, processingResult);
      }} catch (e) {{
        console.error(
          `Error processing event ${{event.type}} (version: ${{event.version}}): ${{e}}`,
        );
      }}
    }}

    return processingResult;
  }}

  /**
   * Process a single event
   */
  async processEvent(
    event: Event,
    processingResult: ProcessingResult,
  ): Promise<void> {{
    // Create base event model
    const eventModel = new Models.{project_name.capitalize()}EventModel();
    eventModel.transactionVersion = event.version;
    eventModel.eventType = event.type;
    eventModel.data = event.data ? JSON.stringify(event.data) : null;
    eventModel.timestamp = new Date(Number(event.timestamp) / 1000);
    
    // Process specific event types
    if (event.type.includes("0x1::coin::DepositEvent")) {{
      await this.processDepositEvent(event, processingResult);
    }} else if (event.type.includes("0x1::coin::WithdrawEvent")) {{
      await this.processWithdrawEvent(event, processingResult);
    }}
    
    // Add base event to processing result 
    processingResult.models.push(eventModel);
  }}

  /**
   * Process a deposit event
   */
  private async processDepositEvent(
    event: Event,
    processingResult: ProcessingResult,
  ): Promise<void> {{
    if (!event.data) {{
      return;
    }}

    try {{
      // Extract event data
      const {{ amount }} = event.data;
      
      // Create deposit model
      const depositModel = new Models.{project_name.capitalize()}DepositModel();
      depositModel.transactionVersion = event.version;
      depositModel.address = event.accountAddress;
      depositModel.amount = BigInt(amount);
      depositModel.timestamp = new Date(Number(event.timestamp) / 1000);
      
      // Add to processing result
      processingResult.models.push(depositModel);
      
      console.log(
        `Processed deposit: ${{event.accountAddress}} (+${{amount}})`,
      );
    }} catch (e) {{
      console.error(`Error processing deposit event: ${{e}}`);
    }}
  }}

  /**
   * Process a withdraw event
   */
  private async processWithdrawEvent(
    event: Event,
    processingResult: ProcessingResult,
  ): Promise<void> {{
    if (!event.data) {{
      return;
    }}

    try {{
      // Extract event data
      const {{ amount }} = event.data;
      
      // Create withdraw model
      const withdrawModel = new Models.{project_name.capitalize()}WithdrawModel();
      withdrawModel.transactionVersion = event.version;
      withdrawModel.address = event.accountAddress;
      withdrawModel.amount = BigInt(amount);
      withdrawModel.timestamp = new Date(Number(event.timestamp) / 1000);
      
      // Add to processing result
      processingResult.models.push(withdrawModel);
      
      console.log(
        `Processed withdraw: ${{event.accountAddress}} (-${{amount}})`,
      );
    }} catch (e) {{
      console.error(`Error processing withdraw event: ${{e}}`);
    }}
  }}
}}

// Register processor
new {project_name.capitalize()}EventProcessor().start();
"""
    

def generate_react_component(name: str, options: str) -> str:
    """Generate a React component for Aptos dApp frontend"""
    use_wallet = "wallet" in options.lower()
    
    wallet_imports = """
import { useWallet } from "@aptos-labs/wallet-adapter-react";
import { AptosClient } from "aptos";
""" if use_wallet else ""
    
    wallet_hooks = """
  const { account, signAndSubmitTransaction } = useWallet();
  const isConnected = !!account;
""" if use_wallet else ""
    
    return f"""
import React, {{ useState }} from "react";{wallet_imports}

export const {name} = () => {{{wallet_hooks}
  const [loading, setLoading] = useState(false);

  // Add your component logic here
  const handleAction = async () => {{
    setLoading(true);
    try {{
      // Your action logic here
      {'''
      // Example transaction if using wallet
      if (account) {
        const payload = {
          type: "entry_function_payload",
          function: "your_module::your_function",
          type_arguments: [],
          arguments: []
        };
        
        const response = await signAndSubmitTransaction(payload);
        console.log("Transaction submitted:", response);
      }
      ''' if use_wallet else '// Implement your action here'}
    }} catch (error) {{
      console.error("Error:", error);
    }} finally {{
      setLoading(false);
    }}
  }};

  return (
    <div className="p-4 border rounded-lg shadow-sm bg-white">
      <h2 className="text-xl font-bold mb-4">{name}</h2>
      
      {'''
      {!isConnected ? (
        <p className="text-gray-500">Please connect your wallet</p>
      ) : (
        <button
          onClick={handleAction}
          disabled={loading}
          className="px-4 py-2 bg-blue-500 text-white rounded-lg disabled:opacity-50"
        >
          {loading ? "Processing..." : "Perform Action"}
        </button>
      )}
      ''' if use_wallet else '''
      <button
        onClick={handleAction}
        disabled={loading}
        className="px-4 py-2 bg-blue-500 text-white rounded-lg disabled:opacity-50"
      >
        {loading ? "Processing..." : "Perform Action"}
      </button>
      '''}
    </div>
  );
}};

export default {name};
"""

def generate_client_function(name: str, options: str) -> str:
    """Generate a client utility function for interacting with Aptos blockchain"""
    return f"""
import {{ AptosClient, Types, HexString }} from "aptos";

// Aptos network configuration
const NODE_URL = process.env.NEXT_PUBLIC_APTOS_NODE_URL || "https://fullnode.devnet.aptoslabs.com";
const client = new AptosClient(NODE_URL);

/**
 * {name} - Utility function for interacting with Aptos blockchain
 * @param args - Function arguments
 * @returns Result of the operation
 */
export async function {name.lower()}(args: any) {{
  try {{
    // Implementation goes here
    // Example: Query resources, submit transactions, etc.
    
    // Example resource query:
    // const resource = await client.getAccountResource(
    //   new HexString(accountAddress),
    //   "0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>"
    // );
    
    return {{
      success: true,
      data: null // Replace with actual data
    }};
  }} catch (error) {{
    console.error(`Error in {name}:`, error);
    return {{
      success: false,
      error: error instanceof Error ? error.message : String(error)
    }};
  }}
}}

// Add more helper functions below
"""

def generate_move_table(name: str, options: str) -> str:
    """Generate a Move table implementation"""
    return f"""
module {name}::table {{
    use std::signer;
    use aptos_framework::account;
    use aptos_framework::table::{{\n        Table,\n        new,\n        add,\n        borrow,\n        borrow_mut,\n        contains,\n        remove\n    }};
    
    // Error codes
    const E_NOT_INITIALIZED: u64 = 1;
    const E_ALREADY_INITIALIZED: u64 = 2;
    const E_KEY_NOT_FOUND: u64 = 3;
    const E_KEY_ALREADY_EXISTS: u64 = 4;
    
    struct {name.capitalize()}Store has key {{
        items: Table<KeyType, ValueType>,
    }}
    
    /// Key type for the table
    struct KeyType has copy, drop, store {{ 
        // Define your key structure
        id: u64,
    }}
    
    /// Value type for the table
    struct ValueType has copy, drop, store {{
        // Define your value structure
        data: u64,
        name: vector<u8>,
    }}
    
    /// Initialize the table
    public entry fun initialize(account: &signer) {{
        let addr = signer::address_of(account);
        assert!(!exists<{name.capitalize()}Store>(addr), E_ALREADY_INITIALIZED);
        
        move_to(account, {name.capitalize()}Store {{
            items: new<KeyType, ValueType>(),
        }});
    }}
    
    /// Add an item to the table
    public entry fun add_item(
        account: &signer, 
        id: u64,
        data: u64,
        name: vector<u8>
    ) acquires {name.capitalize()}Store {{
        let addr = signer::address_of(account);
        assert!(exists<{name.capitalize()}Store>(addr), E_NOT_INITIALIZED);
        
        let store = borrow_mut<{name.capitalize()}Store>(addr);
        let key = KeyType {{ id }};
        
        assert!(!contains(&store.items, key), E_KEY_ALREADY_EXISTS);
        
        add(&mut store.items, key, ValueType {{ 
            data,
            name
        }});
    }}
    
    /// Get an item from the table (public view function)
    #[view]
    public fun get_item(addr: address, id: u64): (u64, vector<u8>) acquires {name.capitalize()}Store {{
        assert!(exists<{name.capitalize()}Store>(addr), E_NOT_INITIALIZED);
        
        let store = borrow<{name.capitalize()}Store>(addr);
        let key = KeyType {{ id }};
        
        assert!(contains(&store.items, key), E_KEY_NOT_FOUND);
        
        let value = borrow(&store.items, key);
        (value.data, value.name)
    }}
    
    /// Remove an item from the table
    public entry fun remove_item(account: &signer, id: u64) acquires {name.capitalize()}Store {{
        let addr = signer::address_of(account);
        assert!(exists<{name.capitalize()}Store>(addr), E_NOT_INITIALIZED);
        
        let store = borrow_mut<{name.capitalize()}Store>(addr);
        let key = KeyType {{ id }};
        
        assert!(contains(&store.items, key), E_KEY_NOT_FOUND);
        
        remove(&mut store.items, key);
    }}
}}
"""

@mcp.tool()
async def test_aptos_contract(contract_path: str, function_name: str = "", args: list = None) -> str:
    """
    Test an Aptos Move contract using the Aptos CLI.
    
    Args:
        contract_path: Path to the contract directory or file
        function_name: Optional function to test specifically
        args: Optional list of arguments for the function
    """
    contract_path = os.path.expanduser(contract_path)  # Expand ~ in paths
    
    if not os.path.exists(contract_path):
        return f"Contract path not found: {contract_path}"
    
    try:
        cmd = ["aptos", "move", "test"]
        
        if os.path.isfile(contract_path):
            cmd.extend(["--path", os.path.dirname(contract_path)])
            if function_name:
                cmd.extend(["--filter", function_name])
        else:
            cmd.extend(["--path", contract_path])
            if function_name:
                cmd.extend(["--filter", function_name])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return f"Tests passed successfully:\n\n{result.stdout}"
        else:
            return f"Tests failed:\n\n{result.stderr}"
    
    except Exception as e:
        return f"Error testing contract: {str(e)}"

@mcp.tool()
async def create_aptos_indexer(project_name: str, processor_type: str = "transaction") -> str:
    """
    Creates a new Aptos indexer project based on the example processor.
    
    Args:
        project_name: Name of the indexer project
        processor_type: Type of processor (transaction, event)
    """
    project_name = project_name.strip().replace(" ", "-").lower()
    
    supported_types = ["transaction", "event"]
    if processor_type not in supported_types:
        return f"Unsupported processor type. Choose from: {', '.join(supported_types)}"
    
    try:
        # Create project directory
        project_dir = os.path.join(os.getcwd(), project_name)
        if os.path.exists(project_dir):
            return f"Directory {project_dir} already exists. Please choose a different name."
        
        os.makedirs(project_dir)
        
        # Clone the example repo to get the template
        temp_dir = os.path.join(tempfile.gettempdir(), "aptos-indexer-example")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        clone_cmd = [
            "git", "clone", "https://github.com/aptos-labs/aptos-indexer-processor-example.git", 
            temp_dir, "--depth", "1"
        ]
        subprocess.run(clone_cmd, check=True, capture_output=True)
        
        # Copy relevant files from template
        shutil.copytree(os.path.join(temp_dir, "typescript"), project_dir, dirs_exist_ok=True)
        
        # Remove the git directory
        git_dir = os.path.join(project_dir, ".git")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir)
        
        # Customize the package.json
        package_json_path = os.path.join(project_dir, "package.json")
        with open(package_json_path, "r") as f:
            package_json = json.load(f)
        
        package_json["name"] = project_name
        package_json["description"] = f"Aptos indexer for {project_name}"
        
        with open(package_json_path, "w") as f:
            json.dump(package_json, f, indent=2)
        
        # Customize processor based on type
        processor_dir = os.path.join(project_dir, "src", "processors")
        os.makedirs(processor_dir, exist_ok=True)
        
        processor_code = ""
        if processor_type == "transaction":
            processor_code = generate_transaction_processor(project_name)
        elif processor_type == "event":
            processor_code = generate_event_processor(project_name)
        
        processor_file = os.path.join(processor_dir, f"{project_name}_processor.ts")
        with open(processor_file, "w") as f:
            f.write(processor_code)
        
        # Create README
        readme_content = f"""# {project_name} Aptos Indexer

An Aptos indexer for processing {processor_type}s.

## Setup

1. Install dependencies:
   ```
   npm install
   ```

2. Configure connection:
   Edit the `.env` file to set your database and Aptos node URLs.

3. Run the indexer:
   ```
   npm run start
   ```

## Architecture

This indexer uses the Aptos Indexer Framework to process {processor_type}s from the Aptos blockchain.

## Development

- `src/processors/{project_name}_processor.ts`: Contains the main processor logic
- `src/models/`: Database models for storing indexed data
"""

        with open(os.path.join(project_dir, "README.md"), "w") as f:
            f.write(readme_content)
        
        # Create .env file
        env_content = """# Aptos Node URL
APTOS_NODE_URL=https://fullnode.devnet.aptoslabs.com/v1

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASS=postgres

# Indexer Configuration
STARTING_VERSION=0
BATCH_SIZE=500
"""
        
        with open(os.path.join(project_dir, ".env"), "w") as f:
            f.write(env_content)
        
        return f"""
Successfully created Aptos indexer project at {project_dir}!

The project includes:
- TypeScript boilerplate for an Aptos indexer
- {processor_type.capitalize()} processor template
- Database models and configurations
- Environment setup

Next steps:
1. Navigate to the project directory: `cd {project_name}`
2. Install dependencies: `npm install`
3. Configure your database in .env
4. Start developing your indexer!

See the README.md file for more information.
"""
    
    except Exception as e:
        return f"Error creating indexer project: {str(e)}"

@mcp.tool()
async def create_gas_station(project_name: str) -> str:
    """
    Creates a new Aptos gas station (fee sponsorship) project.
    
    Args:
        project_name: Name of the gas station project
    """
    project_name = project_name.strip().replace(" ", "-").lower()
    
    try:
        # Create project directory
        project_dir = os.path.join(os.getcwd(), project_name)
        if os.path.exists(project_dir):
            return f"Directory {project_dir} already exists. Please choose a different name."
        
        os.makedirs(project_dir)
        
        # Create server directory
        server_dir = os.path.join(project_dir, "server")
        os.makedirs(server_dir, exist_ok=True)
        
        # Create client directory
        client_dir = os.path.join(project_dir, "client")
        os.makedirs(client_dir, exist_ok=True)
        
        # Generate server files
        server_ts_path = os.path.join(server_dir, "server.ts")
        with open(server_ts_path, "w") as f:
            f.write(generate_gas_station_server())
        
        # Generate client files
        client_ts_path = os.path.join(client_dir, "client.ts")
        with open(client_ts_path, "w") as f:
            f.write(generate_gas_station_client())
        
        # Create package.json for server
        server_package_json = {
            "name": f"{project_name}-server",
            "version": "1.0.0",
            "description": "Aptos Gas Station Server for fee sponsorship",
            "main": "server.ts",
            "scripts": {
                "build": "tsc",
                "start": "ts-node server.ts"
            },
            "dependencies": {
                "@aptos-labs/ts-sdk": "^1.2.0",
                "express": "^4.18.2",
                "dotenv": "^16.3.1"
            },
            "devDependencies": {
                "@types/express": "^4.17.17",
                "ts-node": "^10.9.1",
                "typescript": "^5.1.6"
            }
        }
        
        with open(os.path.join(server_dir, "package.json"), "w") as f:
            json.dump(server_package_json, f, indent=2)
        
        # Create package.json for client
        client_package_json = {
            "name": f"{project_name}-client",
            "version": "1.0.0",
            "description": "Aptos Gas Station Client Example",
            "main": "client.ts",
            "scripts": {
                "build": "tsc",
                "start": "ts-node client.ts"
            },
            "dependencies": {
                "@aptos-labs/ts-sdk": "^1.2.0",
                "axios": "^1.4.0"
            },
            "devDependencies": {
                "ts-node": "^10.9.1",
                "typescript": "^5.1.6"
            }
        }
        
        with open(os.path.join(client_dir, "package.json"), "w") as f:
            json.dump(client_package_json, f, indent=2)
        
        # Create tsconfig.json files
        tsconfig = {
            "compilerOptions": {
                "target": "es2020",
                "module": "commonjs",
                "esModuleInterop": True,
                "forceConsistentCasingInFileNames": True,
                "strict": True,
                "skipLibCheck": True,
                "outDir": "dist"
            }
        }
        
        with open(os.path.join(server_dir, "tsconfig.json"), "w") as f:
            json.dump(tsconfig, f, indent=2)
        
        with open(os.path.join(client_dir, "tsconfig.json"), "w") as f:
            json.dump(tsconfig, f, indent=2)
        
        # Create .env file for server
        env_content = """# Aptos Network: DEVNET, TESTNET, MAINNET
APTOS_NETWORK=DEVNET

# Port for the server
PORT=3000

# Optional: Fund gas account on start (true/false)
AUTO_FUND_ACCOUNT=true
"""
        
        with open(os.path.join(server_dir, ".env"), "w") as f:
            f.write(env_content)
        
        # Create README.md
        readme_content = f"""# {project_name} - Aptos Gas Station

A gas station implementation for Aptos that allows fee sponsorship (fee payer) for transactions.

## Structure

- `server/`: Gas station server that acts as a fee payer
- `client/`: Example client that uses the gas station

## Server Setup

1. Navigate to the server directory:
   ```
   cd server
   ```

2. Install dependencies:
   ```
   npm install
   ```

3. Configure your environment:
   Edit the `.env` file to customize your setup.

4. Start the server:
   ```
   npm start
   ```

## Client Example

The client directory contains an example of how to use the gas station to submit transactions without paying gas fees.

1. Navigate to the client directory:
   ```
   cd client
   ```

2. Install dependencies:
   ```
   npm install
   ```

3. Run the example:
   ```
   npm start
   ```

## How It Works

1. Client builds a transaction and signs it
2. Client sends the transaction to the gas station
3. Gas station signs the transaction as a fee payer
4. Gas station submits the transaction to the blockchain
5. Original transaction executes with fees paid by the gas station

## Security Considerations

- Implement proper authentication for production
- Add rate limiting to prevent abuse
- Monitor gas usage to control costs
"""
        
        with open(os.path.join(project_dir, "README.md"), "w") as f:
            f.write(readme_content)
        
        return f"""
Successfully created Aptos Gas Station project at {project_dir}!

The project includes:
- Server implementation (Express.js)
- Client example code
- Configuration files

Next steps:
1. Navigate to the server directory: `cd {project_name}/server`
2. Install dependencies: `npm install`
3. Configure your environment in .env
4. Start the server: `npm start`

To try the client example:
1. Navigate to the client directory: `cd {project_name}/client`
2. Install dependencies: `npm install`
3. Run the example: `npm start`

See the README.md file for more information.
"""
    
    except Exception as e:
        return f"Error creating gas station project: {str(e)}"

@mcp.tool()
async def aptos_abi_generate(contract_path: str, output_format: str = "ts") -> str:
    """
    Generate ABI for an Aptos contract.
    
    Args:
        contract_path: Path to the contract directory
        output_format: Format of the output (ts, json)
    """
    contract_path = os.path.expanduser(contract_path)  # Expand ~ in paths
    
    if not os.path.exists(contract_path):
        return f"Contract path not found: {contract_path}"
    
    supported_formats = ["ts", "json"]
    if output_format not in supported_formats:
        return f"Unsupported output format. Choose from: {', '.join(supported_formats)}"
    
    try:
        # First compile the contract to get the ABI
        build_cmd = ["aptos", "move", "compile", "--save-metadata", "--path", contract_path]
        build_result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        if build_result.returncode != 0:
            return f"Failed to compile contract:\n\n{build_result.stderr}"
        
        # Find the build directory and ABI files
        build_dir = os.path.join(contract_path, "build")
        if not os.path.exists(build_dir):
            return "Build directory not found after compilation"
        
        # Generate TypeScript client if requested
        if output_format == "ts":
            output_dir = os.path.join(contract_path, "generated")
            os.makedirs(output_dir, exist_ok=True)
            
            # Use aptos CLI to generate TS SDK
            gen_cmd = [
                "aptos", "move", "aptos-sdk-generate", 
                "--output-dir", output_dir,
                "--package-dir", contract_path
            ]
            
            gen_result = subprocess.run(gen_cmd, capture_output=True, text=True)
            
            if gen_result.returncode != 0:
                return f"Failed to generate TypeScript SDK:\n\n{gen_result.stderr}"
            
            return f"Successfully generated TypeScript SDK at {output_dir}"
        
        # If JSON format, just return the ABI files
        abi_files = []
        for root, _, files in os.walk(build_dir):
            for file in files:
                if file.endswith("abi.json"):
                    abi_files.append(os.path.join(root, file))
        
        if not abi_files:
            return "No ABI files found after compilation"
        
        # Return the contents of ABI files
        result = []
        for abi_file in abi_files:
            with open(abi_file, "r") as f:
                abi_content = f.read()
            
            result.append(f"# {os.path.basename(abi_file)}\n```json\n{abi_content}\n```")
        
        return "\n\n".join(result)
    
    except Exception as e:
        return f"Error generating ABI: {str(e)}"

@mcp.prompt()
def create_new_project_prompt() -> str:
    """Prompt template for creating a new Aptos project"""
    return """
I'll help you create a new Aptos blockchain project. Please provide the following information:

1. What would you like to name your project?
2. What type of project do you need? Options are:
   - fullstack (both Move contracts and frontend)
   - contract (Move contracts only)
   - client (frontend only)
3. Any specific requirements or features you're looking to implement?

Once you provide this information, I'll help you set up a new Aptos project with the appropriate structure.
"""

@mcp.prompt()
def debug_move_contract_prompt(error_message: str) -> str:
    """Prompt template for debugging Move contract errors"""
    return f"""
I'll help you debug your Aptos Move contract error. Here's the error you're seeing:

```
{error_message}
```

To better help you resolve this issue, please:

1. Share the relevant Move code where this error occurs
2. Explain what you're trying to accomplish
3. List any additional context about your contract's structure

I'll analyze the error and suggest potential solutions based on Aptos Move best practices.
"""

if __name__ == "__main__":
    # Run the server
    mcp.run()