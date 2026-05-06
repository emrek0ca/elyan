import { NextResponse } from 'next/server';
import {
  ControlPlaneAuthenticationError,
  ControlPlaneConfigurationError,
  ControlPlaneConflictError,
  ControlPlaneEntitlementError,
  ControlPlaneError,
  ControlPlaneInsufficientCreditsError,
  ControlPlaneNotFoundError,
  ControlPlaneProviderError,
  ControlPlaneStoreError,
  ControlPlaneUsageLimitError,
  ControlPlaneValidationError,
} from '@/core/control-plane/errors';

export type ApiErrorResponseInput = {
  status: number;
  code: string;
  message: string;
  issues?: Record<string, string[] | undefined>;
  details?: Record<string, unknown>;
};

function toErrorCode(error: ControlPlaneError) {
  if (error instanceof ControlPlaneAuthenticationError) {
    return 'control_plane_authentication_error';
  }

  if (error instanceof ControlPlaneValidationError) {
    return 'invalid_request';
  }

  if (error instanceof ControlPlaneConflictError) {
    return 'conflict';
  }

  if (error instanceof ControlPlaneNotFoundError) {
    return 'not_found';
  }

  if (error instanceof ControlPlaneEntitlementError) {
    return 'entitlement_required';
  }

  if (error instanceof ControlPlaneConfigurationError) {
    return 'control_plane_configuration_error';
  }

  if (error instanceof ControlPlaneProviderError) {
    return 'provider_error';
  }

  if (error instanceof ControlPlaneInsufficientCreditsError) {
    return 'insufficient_credits';
  }

  if (error instanceof ControlPlaneUsageLimitError) {
    return 'usage_limit_reached';
  }

  if (error instanceof ControlPlaneStoreError) {
    return 'control_plane_store_error';
  }

  return 'control_plane_error';
}

export function createApiErrorResponse(input: ApiErrorResponseInput) {
  return NextResponse.json(
    {
      ok: false,
      error: input.message,
      code: input.code,
      ...(input.issues ? { issues: input.issues } : {}),
      ...(input.details ? { details: input.details } : {}),
    },
    { status: input.status }
  );
}

export function normalizeApiError(
  error: unknown,
  fallback: ApiErrorResponseInput
): ApiErrorResponseInput {
  if (error instanceof SyntaxError) {
    return {
      status: 400,
      code: 'invalid_json_body',
      message: 'Invalid JSON body',
    };
  }

  if (error instanceof ControlPlaneError) {
    return {
      status: error.statusCode,
      code: toErrorCode(error),
      message: error.message,
    };
  }

  if (error && typeof error === 'object' && 'statusCode' in error) {
    return {
      ...fallback,
      status: Number((error as { statusCode: number }).statusCode) || fallback.status,
    };
  }

  return fallback;
}

