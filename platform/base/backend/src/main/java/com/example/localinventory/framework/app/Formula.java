package com.example.localinventory.framework.app;

import java.util.Map;

/** Arithmetic over a row's number fields: + - * / and parentheses, e.g. "quantity * unitPrice". Nothing else is possible. */
public final class Formula {
    private final String text;
    private final Map<String, Double> values;
    private int at;

    private Formula(String text, Map<String, Double> values) { this.text = text; this.values = values; }

    /** The value, or null when a field it needs is empty. Throws IllegalArgumentException for a malformed formula or unknown name. */
    public static Double evaluate(String formula, Map<String, Double> values) {
        Formula parser = new Formula(formula, values);
        Double result = parser.sum();
        parser.skip();
        if (parser.at < parser.text.length()) throw new IllegalArgumentException("계산식을 읽을 수 없습니다: " + formula);
        return result;
    }

    /** Field names a formula uses (for validating a definition). */
    public static java.util.Set<String> names(String formula) {
        java.util.Set<String> out = new java.util.LinkedHashSet<>();
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("[a-z][A-Za-z0-9]*").matcher(formula);
        while (matcher.find()) out.add(matcher.group());
        return out;
    }

    private void skip() { while (at < text.length() && Character.isWhitespace(text.charAt(at))) at++; }

    private Double sum() {
        Double left = product();
        for (skip(); at < text.length() && (text.charAt(at) == '+' || text.charAt(at) == '-'); skip()) {
            char op = text.charAt(at++);
            Double right = product();
            left = left == null || right == null ? null : op == '+' ? left + right : left - right;
        }
        return left;
    }

    private Double product() {
        Double left = unit();
        for (skip(); at < text.length() && (text.charAt(at) == '*' || text.charAt(at) == '/'); skip()) {
            char op = text.charAt(at++);
            Double right = unit();
            left = left == null || right == null ? null : op == '*' ? left * right : right == 0 ? null : left / right;
        }
        return left;
    }

    private Double unit() {
        skip();
        if (at >= text.length()) throw new IllegalArgumentException("계산식이 중간에 끝났습니다: " + text);
        char c = text.charAt(at);
        if (c == '(') {
            at++;
            Double inner = sum();
            skip();
            if (at >= text.length() || text.charAt(at) != ')') throw new IllegalArgumentException("괄호가 닫히지 않았습니다: " + text);
            at++;
            return inner;
        }
        int start = at;
        if (Character.isDigit(c)) {
            while (at < text.length() && (Character.isDigit(text.charAt(at)) || text.charAt(at) == '.')) at++;
            return Double.parseDouble(text.substring(start, at));
        }
        if (Character.isLetter(c)) {
            while (at < text.length() && Character.isLetterOrDigit(text.charAt(at))) at++;
            String name = text.substring(start, at);
            if (!values.containsKey(name)) throw new IllegalArgumentException("계산식의 " + name + " 항목이 없습니다");
            return values.get(name);
        }
        throw new IllegalArgumentException("계산식을 읽을 수 없습니다: " + text);
    }
}
