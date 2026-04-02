#!/usr/bin/env node

import { spawn } from "node:child_process";
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

/**
 * Locate the best Python executable to use.
 * Priority:
 * 1. Local venv inside the project
 * 2. System python3
 */
function getPythonExecutable(): string {
  const venvPath = join(projectRoot, "venv", "bin", "python3");
  if (existsSync(venvPath)) {
    return venvPath;
  }
  return "python3";
}

const pythonExecutable = getPythonExecutable();

/**
 * Start the Python MCP Server and bridge standard I/O.
 */
function startBridge() {
  const pythonProcess = spawn(pythonExecutable, [pythonScriptPath], {
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
