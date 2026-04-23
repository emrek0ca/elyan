import { all, create } from 'mathjs';
import Decimal from 'decimal.js';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

const math = create(all, {
  number: 'number',
  precision: 64,
});

const mathExactInputSchema = z.object({
  expression: z.string().min(1),
});

const mathExactOutputSchema = z.object({
  value: z.string(),
  formatted: z.string(),
});

const decimalInputSchema = z.object({
  left: z.string().min(1),
  right: z.string().min(1),
  operation: z.enum(['add', 'subtract', 'multiply', 'divide']),
});

const decimalOutputSchema = z.object({
  value: z.string(),
});

export { mathExactInputSchema, mathExactOutputSchema, decimalInputSchema, decimalOutputSchema };

export function evaluateExactMath(expression: string) {
  const value = math.evaluate(expression);

  return {
    value: math.format(value, { precision: 64 }),
    formatted: math.format(value),
  };
}

export function calculateDecimalMath(
  left: string,
  right: string,
  operation: 'add' | 'subtract' | 'multiply' | 'divide'
) {
  const decimalLeft = new Decimal(left);
  const decimalRight = new Decimal(right);

  const result = (() => {
    switch (operation) {
      case 'add':
        return decimalLeft.add(decimalRight);
      case 'subtract':
        return decimalLeft.sub(decimalRight);
      case 'multiply':
        return decimalLeft.mul(decimalRight);
      case 'divide':
        return decimalLeft.div(decimalRight);
    }
  })();

  return {
    value: result.toString(),
  };
}

export const mathExactCapability: CapabilityDefinition<
  typeof mathExactInputSchema,
  typeof mathExactOutputSchema
> = {
  id: 'math_exact',
  title: 'Exact Math',
  description: 'Evaluates deterministic math expressions with mathjs.',
  library: 'mathjs',
  enabled: true,
  timeoutMs: 250,
  inputSchema: mathExactInputSchema,
  outputSchema: mathExactOutputSchema,
  run: async (input: z.output<typeof mathExactInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return evaluateExactMath(input.expression);
  },
};

export const decimalMathCapability: CapabilityDefinition<
  typeof decimalInputSchema,
  typeof decimalOutputSchema
> = {
  id: 'math_decimal',
  title: 'Decimal Math',
  description: 'Performs high precision decimal arithmetic with decimal.js.',
  library: 'decimal.js',
  enabled: true,
  timeoutMs: 250,
  inputSchema: decimalInputSchema,
  outputSchema: decimalOutputSchema,
  run: async (input: z.output<typeof decimalInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return calculateDecimalMath(input.left, input.right, input.operation);
  },
};
