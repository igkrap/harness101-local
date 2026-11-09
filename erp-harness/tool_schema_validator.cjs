const fs = require('fs');
const Ajv = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/ajv');

(async () => {
  try {
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    const ajv = new Ajv({ allErrors: true, jsonPointers: true, strict: false });
    const validate = ajv.compile(input.schema);
    const valid = validate(input.arguments);
    console.log(JSON.stringify({ valid, errors: validate.errors || [] }));
  } catch (e) {
    const isParseError = e instanceof SyntaxError;
    console.log(JSON.stringify({
      valid: false,
      internal_error: String(e.message),
      errors: []
    }));
    process.exit(1);
  }
})();
