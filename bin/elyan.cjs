#!/usr/bin/env node

const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const packageRoot = path.resolve(__dirname, "..");
const stateDir = path.join(os.homedir(), ".elyan", "npm-runtime");
const venvDir = path.join(stateDir, "venv");
const stampPath = path.join(stateDir, "install-stamp.json");

function run(command, args, options = {}) {
  const result = childProcess.spawnSync(command, args, {
    stdio: options.stdio || "inherit",
    cwd: options.cwd || packageRoot,
    env: { ...process.env, ...(options.env || {}) },
  });
  if (result.error) {
    throw result.error;
  }
  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
}

function findPython() {
  for (const candidate of ["python3", "python"]) {
    const result = childProcess.spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (result.status === 0) {
      return candidate;
    }
  }
  console.error("Elyan requires Python 3.11+. Install python3 first.");
  process.exit(1);
}

function readStamp() {
  try {
    return JSON.parse(fs.readFileSync(stampPath, "utf8"));
  } catch {
    return null;
  }
}

function packageVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")).version || "0.0.0";
  } catch {
    return "0.0.0";
  }
}

function ensureRuntime() {
  fs.mkdirSync(stateDir, { recursive: true });
  const stamp = readStamp();
  const currentVersion = packageVersion();
  const python = findPython();
  const venvPython = path.join(venvDir, "bin", "python");

  if (!fs.existsSync(venvPython) || !stamp || stamp.version !== currentVersion) {
    run(python, ["-m", "venv", venvDir]);
    run(venvPython, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]);
    run(venvPython, ["-m", "pip", "install", "--upgrade", packageRoot]);
    fs.writeFileSync(stampPath, JSON.stringify({ version: currentVersion }, null, 2));
  }
}

function main() {
  ensureRuntime();
  const executable = path.join(venvDir, "bin", "elyan");
  const child = childProcess.spawn(executable, process.argv.slice(2), { stdio: "inherit" });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code || 0);
  });
}

main();
