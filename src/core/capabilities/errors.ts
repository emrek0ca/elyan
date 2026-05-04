export class CapabilityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CapabilityError';
  }
}

export class CapabilityNotFoundError extends CapabilityError {
  constructor(capabilityId: string) {
    super(`Capability not found: ${capabilityId}`);
    this.name = 'CapabilityNotFoundError';
  }
}

export class CapabilityDisabledError extends CapabilityError {
  constructor(capabilityId: string, reason: string) {
    super(`Capability disabled: ${capabilityId} (${reason})`);
    this.name = 'CapabilityDisabledError';
  }
}

export class CapabilityTimeoutError extends CapabilityError {
  constructor(capabilityId: string, timeoutMs: number) {
    super(`Capability timed out: ${capabilityId} after ${timeoutMs}ms`);
    this.name = 'CapabilityTimeoutError';
  }
}

