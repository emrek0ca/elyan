import type { DefaultSession } from 'next-auth';

declare module 'next-auth' {
  interface Session {
    user: DefaultSession['user'] & {
      id?: string;
      accountId?: string;
      ownerType?: string;
      role?: string;
      planId?: string;
    };
  }

  interface User {
    id: string;
    accountId?: string;
    ownerType?: string;
    role?: string;
    planId?: string;
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    accountId?: string;
    ownerType?: string;
    role?: string;
    planId?: string;
  }
}
