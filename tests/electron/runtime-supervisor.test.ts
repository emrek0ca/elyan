import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolveRuntimeLaunch } from '../../src/main/runtime-supervisor';

describe('runtime launch resolution', () => {
  it('prefers bundled runtime when present', () => {
    const resourcesPath = '/app/resources';
    const bundled = path.join(resourcesPath, 'runtime', 'macos', 'elyan-runtime', 'elyan-runtime');
    const launch = resolveRuntimeLaunch({
      workspaceRoot: '/workspace',
      resourcesPath,
      packaged: true,
      platform: 'darwin',
      exists: (candidate) => candidate === bundled,
    });

    expect(launch?.mode).toBe('bundled');
    expect(launch?.executable).toBe(bundled);
  });

  it('prefers bridge.py in dev even when a bundled runtime already exists', () => {
    const workspaceRoot = '/workspace';
    const resourcesPath = '/resources';
    const bridge = path.join(workspaceRoot, 'runtime', 'bridge.py');
    const bundled = path.join(resourcesPath, 'runtime', 'macos', 'elyan-runtime', 'elyan-runtime');
    const launch = resolveRuntimeLaunch({
      workspaceRoot,
      resourcesPath,
      packaged: false,
      platform: 'darwin',
      environment: { ELYAN_DESKTOP_PYTHON: '/bin/python-dev' },
      exists: (candidate) => candidate === bridge || candidate === bundled || candidate === '/bin/python-dev',
    });

    expect(launch?.mode).toBe('python');
    expect(launch?.executable).toBe('/bin/python-dev');
    expect(launch?.args).toEqual([bridge]);
    expect(launch?.packagedBinaryAvailable).toBe(true);
  });

  it('falls back to bridge.py with direct argv launch', () => {
    const workspaceRoot = '/workspace';
    const bridge = path.join(workspaceRoot, 'runtime', 'bridge.py');
    const launch = resolveRuntimeLaunch({
      workspaceRoot,
      resourcesPath: '/resources',
      packaged: false,
      platform: 'linux',
      environment: { ELYAN_DESKTOP_PYTHON: '/bin/python-custom' },
      exists: (candidate) => candidate === bridge || candidate === '/bin/python-custom',
    });

    expect(launch?.mode).toBe('python');
    expect(launch?.executable).toBe('/bin/python-custom');
    expect(launch?.args).toEqual([bridge]);
  });

  it('returns null when no runtime path exists', () => {
    const launch = resolveRuntimeLaunch({
      workspaceRoot: '/workspace',
      resourcesPath: '/resources',
      packaged: false,
      platform: 'win32',
      exists: () => false,
    });

    expect(launch).toBeNull();
  });
});
