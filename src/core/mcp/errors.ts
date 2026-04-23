export class McpError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'McpError';
  }
}

export class McpUnavailableError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpUnavailableError';
  }
}

export class McpTimeoutError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpTimeoutError';
  }
}

export class McpCancelledError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpCancelledError';
  }
}

export class McpMalformedResponseError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpMalformedResponseError';
  }
}

export class McpDisabledError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpDisabledError';
  }
}

export class McpBlockedError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = 'McpBlockedError';
  }
}
