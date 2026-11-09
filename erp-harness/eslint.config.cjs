const path = require('path');
const os = require('os');
const globals = require(os.homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/globals');

const deps = path.join(os.homedir(), '.local/share/mlx-server/code-intelligence/node_modules/');
const parser = require(deps + '@typescript-eslint/parser/dist/index.js');
const tsPlugin = require(deps + '@typescript-eslint/eslint-plugin/dist/index.js');
const hooks = require(deps + 'eslint-plugin-react-hooks');

module.exports = [
  {
    ignores: ['**/node_modules/**', '**/dist/**', '**/*.d.ts'],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      parser: parser,
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2021 },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': hooks,
    },
    rules: {
      'no-constant-condition': 'error',
      'no-unreachable': 'error',
      'no-debugger': 'error',
      'no-duplicate-case': 'error',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'constructor-super': 'error',
      'no-this-before-super': 'error',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { 
        argsIgnorePattern: '^_', 
        varsIgnorePattern: '^_', 
        caughtErrorsIgnorePattern: '^_', 
        ignoreRestSiblings: true 
      }],
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
];
