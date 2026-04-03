#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync, mkdirSync, writeFileSync, openSync, closeSync } from "node:fs";
import { homedir } from "node:os";

// Get the directory of the current module
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Root of the project
const projectRoot = join(__dirname, "..");

// Path to the Python script
const pythonScriptPath = join(projectRoot, "src", "mcp_server.py");

// Store the virtual environment in the user's App Support directory to avoid EACCES permission errors
const appSupportDir = join(homedir(), "Library", "Application Support", "VoiceMCP");
const venvPath = join(appSupportDir, "venv");
const venvPythonPath = join(venvPath, "bin", "python3");
const requirementsPath = join(projectRoot, "requirements.txt");
const setupMarker = join(venvPath, ".setup_complete");
const setupLogPath = join(appSupportDir, "setup.log");

/**
 * Strips npm/npx specific environment variables that can break Python virtual environments.
 */
function cleanEnv(): NodeJS.ProcessEnv {
  const env: Record<string, string | undefined> = { ...process.env, PYTHONUNBUFFERED: "1", PIP_REQUIRE_VIRTUALENV: "false" };
  for (const key in env) {
    if (key.toLowerCase().startsWith("npm_")) {
      delete env[key];
    }
  }
  return env as NodeJS.ProcessEnv;
}

/**
 * Ensures the Python virtual environment exists and dependencies are installed.
 */
function ensurePythonEnvironment() {
  if (!existsSync(setupMarker)) {
    console.error("Voice MCP: Initializing Python virtual environment. This may take a minute...");
    
    // Ensure Application Support directory exists
    if (!existsSync(appSupportDir)) {
      mkdirSync(appSupportDir, { recursive: true });
    }

    // Create the virtual environment
    const venvResult = spawnSync("python3", ["-m", "venv", venvPath], {
      cwd: projectRoot,
      stdio: "ignore",
      env: cleanEnv()
    });

    if (venvResult.status !== 0) {
      console.error("Voice MCP: Failed to create Python virtual environment.");
      process.exit(1);
    }

    console.error(`Voice MCP: Installing ML dependencies. This can take several minutes. Log: ${setupLogPath}`);
    
    const outFd = openSync(setupLogPath, "w");

    // Install requirements
    const pipResult = spawnSync(venvPythonPath, ["-m", "pip", "install", "-r", requirementsPath], {
      cwd: projectRoot,
      stdio: ["ignore", outFd, outFd],
      env: cleanEnv()
    });

    closeSync(outFd);

    if (pipResult.status !== 0) {
      console.error(`Voice MCP: Failed to install Python dependencies. Please check the log at ${setupLogPath}`);
      process.exit(1);
    }
    
    writeFileSync(setupMarker, "done");
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
    env: cleanEnv()
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

