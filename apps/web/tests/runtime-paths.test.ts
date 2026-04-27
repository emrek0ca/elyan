import { describe, expect, it } from 'vitest';
import { getGlobalEnvPath, resolveGlobalConfigDir, resolveRuntimeSettingsPath } from '@/lib/runtime-paths';

describe('runtime paths', () => {
  it('resolves the global config directory and env file from an explicit home directory', () => {
    expect(resolveGlobalConfigDir('/Users/elyan')).toBe('/Users/elyan/.elyan');
    expect(getGlobalEnvPath('/Users/elyan')).toBe('/Users/elyan/.elyan/.env');
  });

  it('resolves workspace-relative runtime settings paths deterministically', () => {
    expect(resolveRuntimeSettingsPath('storage/runtime/settings.json', '/Users/elyan/project')).toBe(
      '/Users/elyan/project/storage/runtime/settings.json'
    );
  });
});
