#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

// Get the directory of the current module
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Root of the project
const projectRoot = join(__dirname, "..");

// Path to the Python script
const pythonScriptPath = join(projectRoot, "src", "mcp_server.py");
const venvPath = join(projectRoot, "venv");
const venvPythonPath = join(venvPath, "bin", "python3");
const requirementsPath = join(projectRoot, "requirements.txt");

/**
 * Ensures the Python virtual environment exists and dependencies are installed.
 */
function ensurePythonEnvironment() {
  if (!existsSync(venvPath)) {
    console.error("Voice MCP: Initializing Python virtual environment. This may take a minute...");
    
    // Create the virtual environment
    const venvResult = spawnSync("python3", ["-m", "venv", "venv"], {
      cwd: projectRoot,
      stdio: "inherit"
    });

    if (venvResult.status !== 0) {
      console.error("Voice MCP: Failed to create Python virtual environment.");
      process.exit(1);
    }

    console.error("Voice MCP: Installing ML dependencies (silero-vad, mlx-whisper, kokoro, etc.)...");
    
    // Install requirements
    const pipResult = spawnSync(venvPythonPath, ["-m", "pip", "install", "-r", requirementsPath], {
      cwd: projectRoot,
      stdio: "inherit"
    });

    if (pipResult.status !== 0) {
      console.error("Voice MCP: Failed to install Python dependencies.");
      process.exit(1);
    }
    
    console.error("Voice MCP: Environment setup complete!");
  }
}

/**
 * Start the Python MCP Server and bridge standard I/O.
 */
function startBridge() {
  ensurePythonEnvironment();

  const pythonProcess = spawn(venvPythonPath, [pythonScriptPath], {
    stdio: ["pipe", "pipe", "inherit"],
    env: {
      ...process.env,
      // Ensure Python output isn't buffered
      PYTHONUNBUFFERED: "1",
    },
  });

  // Pipe our stdin into Python's stdin
  process.stdin.pipe(pythonProcess.stdin!);

  // Pipe Python's stdout back to our stdout
  pythonProcess.stdout!.pipe(process.stdout);

  // Handle process termination
  pythonProcess.on("exit", (code) => {
    process.exit(code ?? 0);
  });

  // Forward signals
  process.on("SIGINT", () => pythonProcess.kill("SIGINT"));
  process.on("SIGTERM", () => pythonProcess.kill("SIGTERM"));
}

startBridge();

