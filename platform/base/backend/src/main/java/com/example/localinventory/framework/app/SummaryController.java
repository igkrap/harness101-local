package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * A summary screen's numbers: the source entity's rows (or its lines), filtered, grouped and computed as the
 * definition says. Program permissions apply through the path (/api/summary/{key} belongs to the screen's program).
 */
@RestController
public class SummaryController {
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final SystemAccessService access;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final RecordStore store;
    public SummaryController(AppDefinitions definitions, JdbcTemplate jdbc, SystemAccessService access, RecordStore store) {
        this.definitions = definitions; this.jdbc = jdbc; this.access = access; this.store = store;
    }

    private static final class Sums { double sum; double min = Double.POSITIVE_INFINITY, max = Double.NEGATIVE_INFINITY; long numbers, units; }

    /** Filters: <field>=value (equal), <dateField>_from / <dateField>_to (a period), status=<code>. */
    @GetMapping("/api/summary/{key}")
    public Map<String, Object> run(@PathVariable String key, @RequestParam Map<String, String> parameters, Authentication authentication) {
        AppDefinitions.Stored stored = definitions.find(key);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        if (stored == null || stored.definition().summary() == null || (!stored.status().equals("PUBLISHED") && !admin))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "집계 화면을 찾지 못했습니다: " + key);
        AppDefinitions.Summary summary = stored.definition().summary();
        AppDefinitions.Stored sourceStored = definitions.find(summary.entity());
        if (sourceStored == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "모을 자료 " + summary.entity() + " 의 화면이 없어졌습니다.");
        AppDefinitions.Definition source = sourceStored.definition();

        AppDefinitions.Compare compare = summary.compare();
        int of = 0;                                    // the value the comparison (and the share) is about
        if (compare != null) for (int index = 0; index < summary.values().size(); index++) if (summary.values().get(index).label().equals(compare.value())) of = index;
        String op = summary.values().get(of).op();
        boolean previous = compare != null && compare.type().equals("previous"), minus = compare != null && compare.type().equals("minus"), plan = compare != null && (compare.type().equals("plan") || minus);
        Gathered shown = gather(summary, source, parameters);
        // An earlier period must be there to look up even when the period asked for leaves it out.
        Gathered wide = shown;
        if (previous) {
            Map<String, String> without = new LinkedHashMap<>(parameters);
            without.remove(summary.groupBy().get(0).field() + "_from");
            without.remove(summary.groupBy().get(0).field() + "_to");
            wide = gather(summary, source, without);
        }
        Map<String, Double> planned = new LinkedHashMap<>();
        Map<String, List<String>> keysOf = new LinkedHashMap<>(shown.keysOf());
        if (plan) planned = planned(summary, source, compare, parameters, keysOf);
        java.util.TreeSet<String> ids = new java.util.TreeSet<>(shown.groups().keySet());
        ids.addAll(planned.keySet());

        List<Map<String, Object>> columns = new ArrayList<>();
        for (int index = 0; index < summary.groupBy().size(); index++)
            columns.add(Map.of("key", "g" + index, "label", summary.groupBy().get(index).label(), "kind", "group"));
        for (int index = 0; index < summary.values().size(); index++)
            columns.add(Map.of("key", "v" + index, "label", summary.values().get(index).label(), "kind", "value", "op", summary.values().get(index).op()));
        if (compare != null) {
            columns.add(Map.of("key", "c0", "label", compare.label(), "kind", "compare", "role", "base", "of", "v" + of, "type", compare.type()));
            columns.add(Map.of("key", "c1", "label", minus ? compare.balance() : plan ? "차이" : "증감", "kind", "compare", "role", minus ? "balance" : "difference"));
            columns.add(Map.of("key", "c2", "label", minus ? "진행률(%)" : plan ? "달성률(%)" : "증감률(%)", "kind", "compare", "role", "rate"));
        }
        if (summary.share()) columns.add(Map.of("key", "s0", "label", "구성비(%)", "kind", "share", "of", "v" + of));
        if (summary.cumulative()) columns.add(Map.of("key", "r0", "label", summary.values().get(0).label() + " 누계", "kind", "running", "of", "v0"));

        Map<String, Map<String, String>> names = new LinkedHashMap<>();
        List<Map<String, Object>> rows = new ArrayList<>();
        double baseTotal = 0, actualTotal = 0;
        boolean anyBase = false;
        for (String id : ids) {
            Map<String, Object> out = new LinkedHashMap<>();
            List<String> keys = keysOf.get(id);
            for (int index = 0; index < keys.size(); index++) {
                out.put("g" + index + "Key", keys.get(index));
                out.put("g" + index, groupLabel(summary.groupBy().get(index), source, summary.lines(), keys.get(index), names));
            }
            Sums[] sums = shown.groups().get(id);
            for (int index = 0; index < summary.values().size(); index++)
                out.put("v" + index, sums == null ? (summary.values().get(index).op().equals("sum") || summary.values().get(index).op().equals("count") ? (Object) 0L : null) : result(summary.values().get(index).op(), sums[index]));
            double actual = number(out.get("v" + of));
            actualTotal += actual;
            if (compare != null) {
                Double base = null;
                if (plan) base = minus ? Double.valueOf(planned.getOrDefault(id, 0.0)) : planned.get(id);      // nothing taken away yet is 0, not unknown
                else {
                    List<String> earlier = new ArrayList<>(keys);
                    earlier.set(0, earlier(keys.get(0), compare.by()));
                    Sums[] before = wide.groups().get(String.join("\u0001", earlier));
                    Object value = before == null ? null : result(op, before[of]);
                    base = value == null ? null : Double.valueOf(number(value));
                }
                if (base != null) { baseTotal += base; anyBase = true; }
                out.put("c0", base == null ? null : tidy(base));
                out.put("c1", base == null ? null : tidy(actual - base));
                out.put("c2", minus ? (base == null || actual == 0 ? null : tidy(base / actual * 100))
                        : base == null || base == 0 ? null : tidy(plan ? actual / base * 100 : (actual - base) / base * 100));
            }
            rows.add(out);
        }
        if (summary.share())
            for (Map<String, Object> row : rows) row.put("s0", actualTotal == 0 ? null : tidy(number(row.get("v" + of)) / actualTotal * 100));
        if (summary.cumulative()) {
            double running = 0;
            for (Map<String, Object> row : rows) { running += number(row.get("v0")); row.put("r0", tidy(running)); }
        }
        if (summary.top() != null) {                      // the largest first, by the first value; the totals stay those of everything
            rows.sort((a, b) -> Double.compare(number(b.get("v0")), number(a.get("v0"))));
            if (rows.size() > summary.top()) rows = new ArrayList<>(rows.subList(0, summary.top()));
        }
        Map<String, Object> totals = new LinkedHashMap<>();
        for (int index = 0; index < summary.values().size(); index++) totals.put("v" + index, result(summary.values().get(index).op(), shown.all()[index]));
        if (previous) { totals.put("c0", null); totals.put("c1", null); totals.put("c2", null); }   // earlier periods added together say nothing
        else if (compare != null) {
            double whole = number(totals.get("v" + of));
            totals.put("c0", anyBase ? tidy(baseTotal) : null);
            totals.put("c1", anyBase ? tidy(whole - baseTotal) : null);
            totals.put("c2", minus ? (!anyBase || whole == 0 ? null : tidy(baseTotal / whole * 100))
                    : !anyBase || baseTotal == 0 ? null : tidy(plan ? whole / baseTotal * 100 : (whole - baseTotal) / baseTotal * 100));
        }
        if (summary.share()) totals.put("s0", actualTotal == 0 ? null : (Object) 100L);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("columns", columns);
        out.put("rows", rows);
        out.put("totals", totals);
        return out;
    }

    private record Gathered(Map<String, Sums[]> groups, Map<String, List<String>> keysOf, Sums[] all) {}

    /** The source's rows (or lines) that pass the conditions, added up per group. */
    private Gathered gather(AppDefinitions.Summary summary, AppDefinitions.Definition source, Map<String, String> parameters) {
        Map<String, Sums[]> groups = new TreeMap<>();
        Map<String, List<String>> keysOf = new LinkedHashMap<>();
        Sums[] all = fresh(summary.values().size());
        for (Map<String, Object> row : jdbc.queryForList("SELECT id, data::text AS data, status FROM " + store.source(summary.entity()) + " app_records WHERE entity_key = ? ORDER BY id", summary.entity())) {
            JsonNode header = mapper.readTree((String) row.get("data"));
            String status = (String) row.get("status"), record = String.valueOf(row.get("id"));
            if (!passes(summary, source, header, status, parameters)) continue;
            List<JsonNode> units = new ArrayList<>();
            if (summary.lines()) { for (JsonNode line : header.path("lines")) units.add(line); } else units.add(header);
            for (JsonNode unit : units) {
                List<String> keys = new ArrayList<>();
                for (AppDefinitions.Group group : summary.groupBy()) keys.add(group.field().equals("id") ? record : groupKey(group, source, summary.lines(), header, unit, status));
                String id = String.join("\u0001", keys);
                keysOf.putIfAbsent(id, keys);
                Sums[] sums = groups.computeIfAbsent(id, ignored -> fresh(summary.values().size()));
                for (int index = 0; index < summary.values().size(); index++) {
                    AppDefinitions.Value value = summary.values().get(index);
                    Double number = null;
                    if (value.between() != null) number = days(header, value.between());
                    else if (value.field() != null) {
                        JsonNode from = summary.lines() && unit.has(value.field()) ? unit : header;
                        if (from.hasNonNull(value.field()) && from.get(value.field()).isNumber()) number = from.get(value.field()).asDouble();
                    }
                    add(sums[index], number);
                    add(all[index], number);
                }
            }
        }
        return new Gathered(groups, keysOf, all);
    }

    /** The other entity's numbers per group (a plan, or what is taken away), its fields matched one to one with the summary's groupings (and their conditions). */
    private Map<String, Double> planned(AppDefinitions.Summary summary, AppDefinitions.Definition source, AppDefinitions.Compare compare, Map<String, String> parameters, Map<String, List<String>> keysOf) {
        Map<String, Double> out = new LinkedHashMap<>();
        for (Map<String, Object> row : jdbc.queryForList("SELECT data::text AS data FROM " + store.source(compare.entity()) + " app_records WHERE entity_key = ? ORDER BY id", compare.entity())) {
            JsonNode header = mapper.readTree((String) row.get("data"));
            List<JsonNode> units = new ArrayList<>();
            if (compare.lines()) { for (JsonNode line : header.path("lines")) units.add(line); } else units.add(header);
            for (JsonNode unit : units) {
                List<String> keys = new ArrayList<>();
                boolean pass = true;
                for (int index = 0; index < summary.groupBy().size(); index++) {
                    AppDefinitions.Group group = summary.groupBy().get(index);
                    String mine = compare.groupBy().get(index);
                    JsonNode from = compare.lines() && unit.has(mine) ? unit : header;
                    String value = from.hasNonNull(mine) ? from.get(mine).asString() : "";
                    if (summary.filters().contains(group.field())) {          // a condition on a grouping holds for the other entity as well
                        AppDefinitions.Field field = source.field(group.field());
                        if (field != null && field.type().equals("date")) {
                            String start = parameters.get(group.field() + "_from"), end = parameters.get(group.field() + "_to");
                            if (start != null && !start.isBlank() && (value.isEmpty() || value.compareTo(start.trim()) < 0)) pass = false;
                            if (end != null && !end.isBlank() && (value.isEmpty() || value.compareTo(end.trim()) > 0)) pass = false;
                        } else {
                            String wanted = parameters.get(group.field());
                            if (wanted != null && !wanted.isBlank() && !value.equals(wanted.trim())) pass = false;
                        }
                    }
                    if (group.by() != null && !value.isEmpty())
                        value = group.by().equals("year") ? value.substring(0, Math.min(4, value.length())) : group.by().equals("month") ? value.substring(0, Math.min(7, value.length())) : value;
                    keys.add(value);
                }
                JsonNode holder = compare.lines() && unit.has(compare.field()) ? unit : header;
                if (!pass || !holder.hasNonNull(compare.field()) || !holder.get(compare.field()).isNumber()) continue;
                String id = String.join("\u0001", keys);
                // What is taken away counts only against something that is there (a shipment of an order that is not listed adds no line).
                if (compare.type().equals("minus") && !keysOf.containsKey(id)) continue;
                keysOf.putIfAbsent(id, keys);
                out.merge(id, holder.get(compare.field()).asDouble(), Double::sum);
            }
        }
        return out;
    }

    /** Whole days from the first date field to the second (null when either is empty). */
    private static Double days(JsonNode header, List<String> between) {
        try {
            if (!header.hasNonNull(between.get(0)) || !header.hasNonNull(between.get(1))) return null;
            return (double) java.time.temporal.ChronoUnit.DAYS.between(java.time.LocalDate.parse(header.get(between.get(0)).asString()), java.time.LocalDate.parse(header.get(between.get(1)).asString()));
        } catch (RuntimeException error) { return null; }
    }

    /** The period before: 2026-10 -> 2026-09 (month) or 2025-10 (year); 2026 -> 2025. */
    private static String earlier(String key, String by) {
        try {
            if (key.length() == 4) return String.valueOf(Integer.parseInt(key) - 1);
            java.time.YearMonth month = java.time.YearMonth.parse(key);
            return (by.equals("year") ? month.minusYears(1) : month.minusMonths(1)).toString();
        } catch (RuntimeException error) { return ""; }
    }
    private static double number(Object value) { return value instanceof Number number ? number.doubleValue() : 0; }
    private static Object tidy(double value) {
        double rounded = Math.round(value * 100.0) / 100.0;
        return rounded == Math.rint(rounded) && Math.abs(rounded) < 1e15 ? (Object) (long) rounded : (Object) rounded;
    }

    private static Sums[] fresh(int size) { Sums[] out = new Sums[size]; for (int index = 0; index < size; index++) out[index] = new Sums(); return out; }
    private static void add(Sums sums, Double number) {
        sums.units++;
        if (number == null) return;
        sums.numbers++; sums.sum += number; sums.min = Math.min(sums.min, number); sums.max = Math.max(sums.max, number);
    }
    private static Object result(String op, Sums sums) {
        double value = switch (op) {
            case "count" -> sums.units;
            case "sum" -> sums.sum;
            case "avg" -> sums.numbers == 0 ? Double.NaN : sums.sum / sums.numbers;
            case "min" -> sums.numbers == 0 ? Double.NaN : sums.min;
            default -> sums.numbers == 0 ? Double.NaN : sums.max;
        };
        if (Double.isNaN(value)) return null;
        double rounded = Math.round(value * 10000.0) / 10000.0;
        return rounded == Math.rint(rounded) && Math.abs(rounded) < 1e15 ? (Object) (long) rounded : (Object) rounded;
    }

    private boolean passes(AppDefinitions.Summary summary, AppDefinitions.Definition source, JsonNode header, String status, Map<String, String> parameters) {
        for (String name : summary.filters()) {
            if (name.equals("status")) {
                String wanted = parameters.get("status");
                if (wanted != null && !wanted.isBlank() && !wanted.trim().equals(status)) return false;
                continue;
            }
            AppDefinitions.Field field = source.field(name);
            if (field == null) continue;
            String value = header.hasNonNull(name) ? header.get(name).asString() : "";
            if (field.type().equals("date")) {
                String from = parameters.get(name + "_from"), to = parameters.get(name + "_to");
                if (from != null && !from.isBlank() && (value.isEmpty() || value.compareTo(from.trim()) < 0)) return false;
                if (to != null && !to.isBlank() && (value.isEmpty() || value.compareTo(to.trim()) > 0)) return false;
            } else {
                String wanted = parameters.get(name);
                if (wanted == null || wanted.isBlank()) continue;
                if (field.type().equals("yesno")) { if (RecordController.yes(wanted) != value.equals("true")) return false; }
                else if (field.wordy()) { if (!value.toLowerCase().contains(wanted.trim().toLowerCase())) return false; }
                else if (!value.equals(wanted.trim())) return false;
            }
        }
        return true;
    }

    private static String groupKey(AppDefinitions.Group group, AppDefinitions.Definition source, boolean lines, JsonNode header, JsonNode unit, String status) {
        AppDefinitions.Field field = AppDefinitions.sourceField(source, group.field(), lines);
        if (field == null) return status == null ? "" : status;
        JsonNode from = lines && unit.has(group.field()) ? unit : header;
        String value = from.hasNonNull(group.field()) ? from.get(group.field()).asString() : "";
        if (group.by() != null && !value.isEmpty())
            return group.by().equals("year") ? value.substring(0, Math.min(4, value.length())) : group.by().equals("month") ? value.substring(0, Math.min(7, value.length())) : value;
        return value;
    }

    /** What a group reads as: a record's code and name, a code's name, a status label; dates and plain values as they are. */
    private String groupLabel(AppDefinitions.Group group, AppDefinitions.Definition source, boolean lines, String key, Map<String, Map<String, String>> names) {
        if (key.isEmpty()) return "(없음)";
        if (group.field().equals("id")) {              // a record reads as its own first field (its number or code)
            Map<String, String> known = names.computeIfAbsent("self", ignored -> {
                Map<String, String> out = new LinkedHashMap<>();
                String first = source.fields().isEmpty() ? null : source.fields().get(0).name();
                for (Map<String, Object> row : jdbc.queryForList("SELECT id, data::text AS data FROM " + store.source(source.key()) + " app_records WHERE entity_key = ?", source.key())) {
                    JsonNode data = mapper.readTree((String) row.get("data"));
                    out.put(String.valueOf(row.get("id")), first != null && data.hasNonNull(first) ? data.get(first).asString() : String.valueOf(row.get("id")));
                }
                return out;
            });
            return known.getOrDefault(key, key);
        }
        AppDefinitions.Field field = AppDefinitions.sourceField(source, group.field(), lines);
        if (field == null) return source.status() == null ? key : source.status().label(key);
        if (field.ref() != null) {
            Map<String, String> known = names.computeIfAbsent("ref:" + field.name(), ignored -> {
                Map<String, String> out = new LinkedHashMap<>();
                String code = definitions.codeField(field.ref());
                for (Map<String, Object> row : jdbc.queryForList("SELECT id, data::text AS data FROM " + store.source(field.ref().entity()) + " app_records WHERE entity_key = ?", field.ref().entity())) {
                    JsonNode data = mapper.readTree((String) row.get("data"));
                    String name = data.hasNonNull(field.ref().label()) ? data.get(field.ref().label()).asString() : "";
                    String prefix = code != null && data.hasNonNull(code) ? data.get(code).asString() + " " : "";
                    out.put(String.valueOf(row.get("id")), (prefix + name).trim());
                }
                return out;
            });
            return known.getOrDefault(key, key);
        }
        if (field.type().equals("yesno")) return key.equals("true") ? "예" : "아니오";
        if (field.type().equals("code")) {
            Map<String, String> known = names.computeIfAbsent("code:" + field.codeGroup(), ignored -> {
                Map<String, String> out = new LinkedHashMap<>();
                for (Map<String, Object> row : jdbc.queryForList("SELECT code, code_name FROM sys_codes WHERE group_code = ?", field.codeGroup()))
                    out.put((String) row.get("code"), (String) row.get("code_name"));
                return out;
            });
            return known.getOrDefault(key, key);
        }
        return key;
    }
}
