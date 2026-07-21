import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import { assertAiDataSharingConsent } from "./service.js";

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

function consentApp(input: { required: boolean; granted: boolean }) {
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
            selectCount === 3 && input.granted
              ? [
                  {
                    granted: true,
                    grantedAt: new Date("2030-01-01T00:00:00.000Z"),
                    revokedAt: null,
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
  assert.equal(fixture.selectCount(), 3);
});

test("AI data-sharing consent allows an active grant when enforcement is enabled", async () => {
  const fixture = consentApp({ required: true, granted: true });
  assert.equal(
    await assertAiDataSharingConsent(fixture.app as never, "user-1"),
    true,
  );
  assert.equal(fixture.selectCount(), 3);
});
