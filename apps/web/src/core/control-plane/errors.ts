export class ControlPlaneError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number
  ) {
    super(message);
    this.name = 'ControlPlaneError';
  }
}

export class ControlPlaneNotFoundError extends ControlPlaneError {
  constructor(entity: string, identifier: string) {
    super(`${entity} not found: ${identifier}`, 404);
    this.name = 'ControlPlaneNotFoundError';
  }
}

export class ControlPlaneValidationError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 400);
    this.name = 'ControlPlaneValidationError';
  }
}

export class ControlPlaneAuthenticationError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 401);
    this.name = 'ControlPlaneAuthenticationError';
  }
}

export class ControlPlaneConflictError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 409);
    this.name = 'ControlPlaneConflictError';
  }
}

export class ControlPlaneEntitlementError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 403);
    this.name = 'ControlPlaneEntitlementError';
  }
}

export class ControlPlaneConfigurationError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 503);
    this.name = 'ControlPlaneConfigurationError';
  }
}

export class ControlPlaneProviderError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 502);
    this.name = 'ControlPlaneProviderError';
  }
}

export class ControlPlaneInsufficientCreditsError extends ControlPlaneError {
  constructor(
    message: string,
    public readonly details?: {
      monthlyCreditsRemaining?: string;
      requiredCredits?: string;
      balanceBefore?: string;
      balanceAfter?: string;
      planId?: string;
    }
  ) {
    super(message, 402);
    this.name = 'ControlPlaneInsufficientCreditsError';
  }
}

export class ControlPlaneUsageLimitError extends ControlPlaneError {
  constructor(
    message: string,
    public readonly details?: {
      limitType?: 'daily_requests_limit' | 'daily_tool_action_calls_limit' | 'daily_tokens_limit' | 'per_request_token_limit' | 'run_cost_cap';
      resetAt?: string;
      remainingRequests?: number;
      remainingHostedToolActionCalls?: number;
      remainingTokens?: number;
      monthlyCreditsRemaining?: string;
      planId?: string;
    }
  ) {
    super(message, 429);
    this.name = 'ControlPlaneUsageLimitError';
  }
}

export class ControlPlaneStoreError extends ControlPlaneError {
  constructor(message: string) {
    super(message, 500);
    this.name = 'ControlPlaneStoreError';
  }
}
