export const screenCodePattern = /^[A-Z]{3}[0-9]{4}$/;

export function parseScreenCode(code: string) {
  if (!screenCodePattern.test(code)) throw new Error('Screen code must contain module A–Z, classification AA–ZZ and four digits, for example ABC0001');
  return { code, module: code.slice(0, 1), classification: code.slice(1, 3), sequence: code.slice(3) };
}
