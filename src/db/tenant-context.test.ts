import assert from "node:assert/strict";
import test from "node:test";
import {
  assertTenantMatch,
  buildTenantCacheKey,
  buildTenantNamespace,
} from "./tenant-context.js";

test("tenant cache keys always include the user namespace", () => {
  assert.equal(
    buildTenantNamespace({ userId: "user-1" }),
    "tenant:user-1",
  );
  assert.equal(
    buildTenantCacheKey({
      userId: "user-1",
      scope: "blob:text",
      parts: ["blob/with/slashes", "hash value"],
    }),
    "tenant:user-1:blob:text:blob_with_slashes:hash_value",
  );
});

test("tenant match fails closed for missing or foreign ownership", () => {
  assert.doesNotThrow(() =>
    assertTenantMatch({
      expectedUserId: "user-1",
      actualUserId: "user-1",
      resource: "cache",
    }),
  );
  assert.throws(
    () =>
      assertTenantMatch({
        expectedUserId: "user-1",
        actualUserId: "user-2",
        resource: "cache",
      }),
    /cache_tenant_mismatch/,
  );
  assert.throws(
    () =>
      assertTenantMatch({
        expectedUserId: "user-1",
        actualUserId: null,
        resource: "cache",
      }),
    /cache_tenant_mismatch/,
  );
});
