import { z } from "zod";

export const registerBodySchema = z.object({
  email: z.string().email().max(320),
  password: z.string().min(8).max(128),
  displayName: z.string().min(1).max(120).optional(),
});

export const loginBodySchema = z.object({
  email: z.string().email().max(320),
  password: z.string().min(8).max(128),
});

export const refreshBodySchema = z.object({
  refreshToken: z.string().min(1),
});
