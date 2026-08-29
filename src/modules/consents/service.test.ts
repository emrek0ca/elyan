import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  assertAiDataSharingConsent,
  assertCloudSpeechConsent,
  setUserConsent,
} from "./service.js";

class ConsentQuery {
  constructor(private readonly rows: unknown[]) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit() {
    return Promise.resolve(this.rows);
  }
}

function consentApp(input: {
  required: boolean;
  granted: boolean;
  cloudSpeechGranted?: boolean;
  cloudSpeechRevoked?: boolean;
}) {
  let selectCount = 0;
  return {
    app: {
      config: {
        ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED: input.required,
      },
      db: {
        select() {
          selectCount += 1;
          return new ConsentQuery(
            (selectCount === 3 && input.granted) ||
              ((selectCount === 1 || selectCount === 4) &&
                input.cloudSpeechGranted)
              ? [
                  {
                    granted: true,
                    grantedAt: new Date("2030-01-01T00:00:00.000Z"),
                    revokedAt:
                      (selectCount === 1 || selectCount === 4) &&
                        input.cloudSpeechRevoked
                        ? new Date("2030-01-02T00:00:00.000Z")
                        : null,
                  },
                ]
              : [],
          );
        },
      },
    },
    selectCount: () => selectCount,
  };
}

test("AI data-sharing consent is skipped only while its feature flag is disabled", async () => {
  const fixture = consentApp({ required: false, granted: false });
  assert.equal(
    await assertAiDataSharingConsent(fixture.app as never, "user-1"),
    false,
  );
  assert.equal(fixture.selectCount(), 0);
});

test("AI data-sharing consent fails closed when the feature flag is enabled", async () => {
  const fixture = consentApp({ required: true, granted: false });
  await assert.rejects(
    assertAiDataSharingConsent(fixture.app as never, "user-1"),
    (error: unknown) =>
      error instanceof AppError &&
      error.statusCode === 403 &&
      error.code === "AI_DATA_SHARING_CONSENT_REQUIRED",
  );
  assert.equal(fixture.selectCount(), 5);
});

test("AI data-sharing consent allows an active grant when enforcement is enabled", async () => {
  const fixture = consentApp({ required: true, granted: true });
  assert.equal(
    await assertAiDataSharingConsent(fixture.app as never, "user-1"),
    true,
  );
  assert.equal(fixture.selectCount(), 5);
});

test("cloud speech consent always fails closed without an active grant", async () => {
  const fixture = consentApp({
    required: false,
    granted: true,
    cloudSpeechGranted: false,
  });
  await assert.rejects(
    assertCloudSpeechConsent(fixture.app as never, "user-1"),
    (error: unknown) =>
      error instanceof AppError &&
      error.statusCode === 403 &&
      error.code === "CLOUD_SPEECH_CONSENT_REQUIRED",
  );
  assert.equal(fixture.selectCount(), 1);
});

test("cloud speech consent allows an active explicit grant", async () => {
  const fixture = consentApp({
    required: false,
    granted: true,
    cloudSpeechGranted: true,
  });
  assert.equal(
    await assertCloudSpeechConsent(fixture.app as never, "user-1"),
    true,
  );
  assert.equal(fixture.selectCount(), 1);
});

test("cloud speech consent rejects a stale grant version", async () => {
  await assert.rejects(
    setUserConsent(
      {} as never,
      {
        userId: "user-1",
        consentType: "cloud_speech",
        consentVersion: "2026-07-04",
        granted: true,
        source: "mobile",
      },
    ),
    (error: unknown) =>
      error instanceof AppError && error.code === "consent_version_mismatch",
  );
});

test("revoked cloud speech consent fails closed", async () => {
  const fixture = consentApp({
    required: false,
    granted: true,
    cloudSpeechGranted: true,
    cloudSpeechRevoked: true,
  });
  await assert.rejects(
    assertCloudSpeechConsent(fixture.app as never, "user-1"),
    (error: unknown) =>
      error instanceof AppError &&
      error.code === "CLOUD_SPEECH_CONSENT_REQUIRED",
  );
});
