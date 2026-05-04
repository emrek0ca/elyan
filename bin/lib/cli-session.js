const fs = require('fs');
const path = require('path');

function createCliSessionStore(sessionPath) {
  function readCliSession() {
    if (!fs.existsSync(sessionPath)) {
      return null;
    }

    try {
      return JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
    } catch {
      return null;
    }
  }

  function writeCliSession(session) {
    fs.mkdirSync(path.dirname(sessionPath), { recursive: true });
    fs.writeFileSync(sessionPath, `${JSON.stringify(session, null, 2)}\n`, 'utf8');
  }

  function clearCliSession() {
    if (fs.existsSync(sessionPath)) {
      fs.unlinkSync(sessionPath);
    }
  }

  return {
    readCliSession,
    writeCliSession,
    clearCliSession,
  };
}

function collectSetCookieHeaders(headers) {
  if (typeof headers.getSetCookie === 'function') {
    return headers.getSetCookie();
  }

  const raw = headers.get('set-cookie');
  if (!raw) {
    return [];
  }

  return [raw];
}

function cookiesFromSetCookieHeaders(setCookieHeaders) {
  return setCookieHeaders
    .map((entry) => entry.split(';')[0]?.trim())
    .filter(Boolean)
    .join('; ');
}

function mergeCookieHeader(existing, next) {
  const merged = new Map();

  for (const cookie of [existing, next].filter(Boolean)) {
    for (const part of cookie.split(/;\s*/)) {
      const [name, ...rest] = part.split('=');
      if (!name || rest.length === 0) continue;
      merged.set(name.trim(), rest.join('=').trim());
    }
  }

  return Array.from(merged.entries())
    .map(([name, value]) => `${name}=${value}`)
    .join('; ');
}

function getCliBaseUrl(optionsBaseUrl) {
  return String(optionsBaseUrl || 'http://localhost:3000').replace(/\/$/, '');
}

module.exports = {
  collectSetCookieHeaders,
  cookiesFromSetCookieHeaders,
  createCliSessionStore,
  getCliBaseUrl,
  mergeCookieHeader,
};
