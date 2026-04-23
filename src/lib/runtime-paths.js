/* eslint-disable @typescript-eslint/no-require-imports */
const os = require('os');
const path = require('path');

function getHomeDir() {
  return os.homedir() || process.env.HOME || process.env.USERPROFILE || '';
}

function resolveGlobalConfigDir(homeDir = getHomeDir()) {
  if (!homeDir) {
    return path.resolve(process.cwd(), '.elyan');
  }

  return path.resolve(homeDir, '.elyan');
}

function getGlobalEnvPath(homeDir) {
  return path.join(resolveGlobalConfigDir(homeDir), '.env');
}

function resolveRuntimeSettingsPath(settingsPath = 'storage/runtime/settings.json', cwd = process.cwd()) {
  return path.resolve(cwd, settingsPath);
}

module.exports = {
  getHomeDir,
  resolveGlobalConfigDir,
  getGlobalEnvPath,
  resolveRuntimeSettingsPath,
};
