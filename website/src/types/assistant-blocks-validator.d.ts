declare module '*assistant-blocks.validator.mjs' {
  import type { ValidateFunction } from 'ajv';
  const validate: ValidateFunction;
  export default validate;
}
