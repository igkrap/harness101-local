/** The same arithmetic the server computes with (+ - * / parentheses over a row's numbers), to show values while typing. */
export function evaluate(formula: string, values: Record<string, number | null>): number | null {
  let at = 0;
  const skip = () => { while (at < formula.length && /\s/.test(formula[at])) at++; };
  function unit(): number | null {
    skip();
    if (formula[at] === '(') { at++; const inner = sum(); skip(); at++; return inner; }
    const start = at;
    if (/[0-9]/.test(formula[at] ?? '')) { while (/[0-9.]/.test(formula[at] ?? '')) at++; return Number(formula.slice(start, at)); }
    while (/[A-Za-z0-9]/.test(formula[at] ?? '')) at++;
    return start === at ? null : values[formula.slice(start, at)] ?? null;
  }
  function product(): number | null {
    let left = unit();
    for (skip(); formula[at] === '*' || formula[at] === '/'; skip()) {
      const op = formula[at++], right = unit();
      left = left === null || right === null ? null : op === '*' ? left * right : right === 0 ? null : left / right;
    }
    return left;
  }
  function sum(): number | null {
    let left = product();
    for (skip(); formula[at] === '+' || formula[at] === '-'; skip()) {
      const op = formula[at++], right = product();
      left = left === null || right === null ? null : op === '+' ? left + right : left - right;
    }
    return left;
  }
  return sum();
}
