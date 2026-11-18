package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * A take-over screen: the next stage registered from a list of what the earlier stage still leaves open (shipments from the
 * orders not yet shipped in full). Many records are handled in the list itself - query, tick rows, set the quantity in the
 * row, save; there is no form. What is open is the earlier quantity less what the new entity already holds against it, by the
 * limit the new entity has. The records are made through the entity's own rules (RecordController), all or nothing.
 * The path belongs to the take-over screen's program, so who may do this is decided by who is given the screen.
 */
@RestController
@RequestMapping("/api/take/{key}")
public class TakeController {
    private final AppDefinitions definitions;
    private final RecordController records;
    private final SystemAccessService access;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    public TakeController(AppDefinitions definitions, RecordController records, SystemAccessService access) {
        this.definitions = definitions; this.records = records; this.access = access;
    }
    /** values: what was typed in the row beside the quantity (the fields the screen's definition asks for in the row). */
    /** seen: when the earlier record was last changed as the list showed it - a record changed since is not taken over on what was seen. */
    public record Chosen(long sourceId, int line, Double quantity, Map<String, Object> values, String seen) {}
    /** per: "source" or "same" - how the rows become records this time (the definition's way when not given). */
    public record SaveRequest(Map<String, Object> values, List<Chosen> rows, String per) {}

    private record Plan(AppDefinitions.Take take, AppDefinitions.Definition target, AppDefinitions.Definition earlier, AppDefinitions.Limit limit) {
        List<AppDefinitions.Field> targetLines() { return target.lines() == null ? List.of() : target.lines().fields(); }
        List<AppDefinitions.Field> earlierLines() { return earlier.lines() == null ? List.of() : earlier.lines().fields(); }
        /** Whether a field the limit matches on sits in the new record's lines (else above them). */
        boolean inLine(String name) { return limit.lines() && targetLines().stream().anyMatch(field -> field.name().equals(name)); }
        /** The fields above the lines of the new record that nothing fills: asked once on the screen, for all records made in one save. */
        List<AppDefinitions.Field> asked() {
            List<AppDefinitions.Field> out = new ArrayList<>();
            for (AppDefinitions.Field field : target.fields())
                if (!field.computed() && !take.set().containsKey(field.name()) && !(limit.by().contains(field.name()) && !inLine(field.name())) && !(!limit.lines() && field.name().equals(limit.field()))
                        && !(!limit.lines() && take.ask() != null && take.ask().contains(field.name()))) out.add(field);       // (typed in each row instead)
            return out;
        }
    }

    private Plan plan(String key, Authentication authentication) {
        AppDefinitions.Stored stored = definitions.find(key);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        // a take-over screen, or a screen whose records are made from an earlier list (from): it takes over on its own screen
        AppDefinitions.Take take = stored == null ? null : stored.definition().take() != null ? stored.definition().take() : AppDefinitions.takeOf(stored.definition());
        if (take == null || (!stored.status().equals("PUBLISHED") && !admin))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "화면을 찾지 못했습니다: " + key);
        AppDefinitions.Stored target = definitions.find(take.entity()), earlier = definitions.find(take.from());
        AppDefinitions.Limit limit = target == null || earlier == null ? null : AppDefinitions.takeLimit(target.definition(), take.from());
        if (limit == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "이 화면이 기대는 자료나 한도가 바뀌어 쓸 수 없습니다. 화면을 다시 만들어야 합니다.");
        return new Plan(take, target.definition(), earlier.definition(), limit);
    }

    private static String text(Object value) {
        if (value == null) return "";
        if (value instanceof Double number && number == Math.rint(number) && Math.abs(number) < 1e15) return String.valueOf(number.longValue());
        return String.valueOf(value);
    }
    private static double number(Object value) { return value instanceof Number number ? number.doubleValue() : 0; }
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> linesOf(Map<String, Object> row) { return row.get("lines") instanceof List<?> list ? (List<Map<String, Object>>) list : List.of(); }
    /** The key the limit groups by, for one unit of the earlier entity (a line or the record). */
    private static String keyOf(Plan plan, long id, Map<String, Object> unit, Map<String, Object> row) {
        List<String> keys = new ArrayList<>();
        for (String name : plan.limit().entityBy()) keys.add(name.equals("id") ? String.valueOf(id) : text(unit.containsKey(name) ? unit.get(name) : row.get(name)));
        return String.join(RecordController.SEPARATOR, keys);
    }

    /** What the screen needs to draw itself: the fields to ask once, and how the quantity reads. */
    @GetMapping("/shape")
    public Map<String, Object> shape(@PathVariable String key, Authentication authentication) {
        Plan plan = plan(key, authentication);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("entity", plan.target().key()); out.put("from", plan.earlier().key()); out.put("lines", plan.limit().entityLines());
        out.put("ask", plan.asked().stream().map(AppDefinitions.Field::name).toList());
        out.put("combinable", AppDefinitions.combinable(plan.target(), plan.limit())); out.put("group", plan.take().group() == null ? "source" : plan.take().group());
        out.put("fromTitle", plan.earlier().title());
        List<Map<String, Object>> typed = new ArrayList<>();
        for (String name : plan.take().ask() == null ? List.<String>of() : plan.take().ask())
            for (AppDefinitions.Field field : plan.limit().lines() ? plan.targetLines() : plan.target().fields())
                if (field.name().equals(name)) { Map<String, Object> one = new LinkedHashMap<>(); one.put("name", name); one.put("label", field.label()); one.put("type", field.type()); one.put("required", field.required()); typed.add(one); }
        out.put("askLines", typed);
        AppDefinitions.Ledger ledger = plan.target().ledger();
        if (ledger != null && ledger.direction().equals("out") && ledger.lot() != null && plan.take().ask() != null && plan.take().ask().contains(ledger.lot())) {
            // the lot typed in a row can be chosen from the lots in stock: which field of the earlier line is the item, and where the warehouse comes from
            Map<String, Object> pick = new LinkedHashMap<>();
            pick.put("field", ledger.lot());
            int at = plan.limit().by().indexOf(ledger.thing());
            pick.put("thing", at >= 0 ? plan.limit().entityBy().get(at) : plan.take().lineSet().get(ledger.thing()));
            pick.put("placeAsked", plan.asked().stream().anyMatch(field -> field.name().equals(ledger.place())) ? ledger.place() : null);
            pick.put("placeFrom", plan.take().set().get(ledger.place()));
            out.put("lotPick", pick);
        }
        out.put("quantity", plan.limit().counted() ? null : plan.limit().entityField()); out.put("once", plan.limit().counted()); out.put("columns", plan.take().columns());
        AppDefinitions.Field made = AppDefinitions.sourceField(plan.target(), plan.limit().field(), plan.limit().lines());
        out.put("quantityLabel", made == null ? "수량" : made.label()); out.put("decimals", made == null ? null : made.decimals());
        return out;
    }

    /** The open rows: one per line of the earlier entity (or per record, when the limit is on its header) that is not used up yet. */
    @GetMapping
    public List<Map<String, Object>> list(@PathVariable String key, @RequestParam Map<String, String> filters, Authentication authentication, jakarta.servlet.http.HttpServletResponse response) {
        Plan plan = plan(key, authentication);
        Map<String, String> asked = new LinkedHashMap<>(filters);
        asked.putIfAbsent("_limit", "2000");
        List<Map<String, Object>> found = records.page(plan.earlier(), asked, plan.take().statuses()).rows();
        Map<String, Double> done = records.sums(plan.target().key(), plan.limit().field(), plan.limit().lines(), plan.limit().by(), plan.limit().ignore(), null);
        Map<String, Double> left = new LinkedHashMap<>();           // what is still open per key, shared by rows with the same key
        List<Map<String, Object>> out = new ArrayList<>(), lineUnits = new ArrayList<>();
        for (Map<String, Object> row : found) {
            if (row.get("status") != null && plan.limit().entityIgnore().contains((String) row.get("status"))) continue;
            if (plan.earlier().status() != null && plan.earlier().status().isClosed((String) row.get("status"))) continue;     // finished: what it left open is not offered
            long id = ((Number) row.get("id")).longValue();
            List<Map<String, Object>> units = plan.limit().entityLines() ? linesOf(row) : List.of(row);
            for (Map<String, Object> unit : units) {
                String group = keyOf(plan, id, unit, row);
                left.merge(group, plan.limit().once() ? 1.0 : number(unit.containsKey(plan.limit().entityField()) ? unit.get(plan.limit().entityField()) : row.get(plan.limit().entityField())), Double::sum);
            }
        }
        for (Map.Entry<String, Double> entry : left.entrySet()) entry.setValue(entry.getValue() - done.getOrDefault(entry.getKey(), 0.0));
        for (Map<String, Object> row : found) {
            if (row.get("status") != null && plan.limit().entityIgnore().contains((String) row.get("status"))) continue;
            if (plan.earlier().status() != null && plan.earlier().status().isClosed((String) row.get("status"))) continue;     // finished: what it left open is not offered
            long id = ((Number) row.get("id")).longValue();
            List<Map<String, Object>> units = plan.limit().entityLines() ? linesOf(row) : List.of(row);
            Map<String, Object> head = new LinkedHashMap<>(row);
            head.remove("lines");
            for (int index = 0; index < units.size(); index++) {
                Map<String, Object> unit = units.get(index);
                String group = keyOf(plan, id, unit, row);
                double ordered = plan.limit().once() ? 1.0 : number(unit.containsKey(plan.limit().entityField()) ? unit.get(plan.limit().entityField()) : row.get(plan.limit().entityField()));
                double open = Math.min(ordered, left.getOrDefault(group, 0.0));
                if (open <= 1e-9) continue;
                left.merge(group, -open, Double::sum);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("key", id + ":" + index); item.put("sourceId", id); item.put("line", index); item.put("head", head);
                if (plan.limit().entityLines()) { Map<String, Object> line = new LinkedHashMap<>(unit); item.put("unit", line); lineUnits.add(line); }
                item.put("ordered", ordered); item.put("done", ordered - open); item.put("remaining", open);
                out.add(item);
            }
        }
        if (!lineUnits.isEmpty()) records.named(plan.earlierLines(), lineUnits);      // the lines' own references read as code and name too
        response.setHeader("X-Total-Count", String.valueOf(out.size()));
        return out;
    }

    /** Make the next-stage records from the chosen rows: rows that give the same values above the lines go into one record. All or nothing. */
    @PostMapping
    @Transactional
    public Map<String, Object> save(@PathVariable String key, @RequestBody SaveRequest request, Authentication authentication) {
        Plan plan = plan(key, authentication);
        if (request.rows() == null || request.rows().isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "목록에서 넘길 줄을 고르세요.");
        if (request.rows().size() > 500) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "한 번에 500줄까지 넘길 수 있습니다.");
        java.util.Set<String> askedNames = new java.util.LinkedHashSet<>(plan.asked().stream().map(AppDefinitions.Field::name).toList());
        String per = request.per() == null || request.per().isBlank() ? (plan.take().group() == null ? "source" : plan.take().group()) : request.per();
        if (!per.equals("source") && !per.equals("same")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "묶는 기준을 알 수 없습니다: " + per);
        if (per.equals("same") && !AppDefinitions.combinable(plan.target(), plan.limit())) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "이 자료는 앞 단계 한 건마다 한 건으로만 만들 수 있습니다.");
        Map<String, ObjectNode> bodies = new LinkedHashMap<>();
        List<ObjectNode> singles = new ArrayList<>();
        int number = 0;
        for (Chosen chosen : request.rows()) {
            number++;
            if (!plan.limit().counted() && (chosen.quantity() == null || chosen.quantity() <= 0)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "고른 " + number + "번째 줄: 수량을 0 보다 크게 적으세요.");
            Map<String, Object> source = records.get(plan.earlier().key(), chosen.sourceId(), authentication);
            if (chosen.seen() != null && !chosen.seen().isBlank() && !chosen.seen().trim().equals(String.valueOf(source.get("updatedAt"))))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "고른 " + number + "번째 줄: 조회한 뒤에 다른 사람이 바꾼 자료입니다. 다시 조회한 뒤 저장하세요.");
            if (!plan.take().statuses().isEmpty() && !plan.take().statuses().contains((String) source.get("status")))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "고른 " + number + "번째 줄: 그 사이 상태가 바뀌어 이 화면에서 넘길 수 없습니다.");
            List<Map<String, Object>> units = plan.limit().entityLines() ? linesOf(source) : List.of(source);
            if (chosen.line() < 0 || chosen.line() >= units.size()) throw new ResponseStatusException(HttpStatus.CONFLICT, "고른 " + number + "번째 줄: 그 사이 내용이 바뀌었습니다. 다시 조회하세요.");
            Map<String, Object> unit = units.get(chosen.line());
            ObjectNode head = mapper.createObjectNode(), line = mapper.createObjectNode();
            if (request.values() != null) for (Map.Entry<String, Object> entry : request.values().entrySet()) if (askedNames.contains(entry.getKey())) head.set(entry.getKey(), mapper.valueToTree(entry.getValue()));
            for (Map.Entry<String, String> entry : plan.take().set().entrySet()) {
                if (entry.getValue().equals("id")) head.put(entry.getKey(), chosen.sourceId());
                else if (entry.getValue().equals("today")) head.put(entry.getKey(), RecordController.today().toString());
                else head.set(entry.getKey(), mapper.valueToTree(unit.containsKey(entry.getValue()) && unit != source ? unit.get(entry.getValue()) : source.get(entry.getValue())));
            }
            for (int index = 0; index < plan.limit().by().size(); index++) {
                String into = plan.limit().by().get(index), come = plan.limit().entityBy().get(index);
                Object value = come.equals("id") ? Long.valueOf(chosen.sourceId()) : unit.containsKey(come) ? unit.get(come) : source.get(come);
                (plan.inLine(into) ? line : head).set(into, mapper.valueToTree(value));
            }
            for (Map.Entry<String, String> entry : plan.take().lineSet().entrySet()) line.set(entry.getKey(), mapper.valueToTree(unit.containsKey(entry.getValue()) ? unit.get(entry.getValue()) : source.get(entry.getValue())));
            if (chosen.values() != null && plan.take().ask() != null)
                for (String name : plan.take().ask()) if (chosen.values().get(name) != null && !String.valueOf(chosen.values().get(name)).isBlank()) (plan.limit().lines() ? line : head).set(name, mapper.valueToTree(chosen.values().get(name)));
            if (plan.limit().lines()) {
                if (!plan.limit().counted()) line.put(plan.limit().field(), chosen.quantity());
                ObjectNode body = bodies.computeIfAbsent(head.toString() + (per.equals("source") ? "#" + chosen.sourceId() : ""), same -> { head.set("lines", mapper.createArrayNode()); return head; });
                ((ArrayNode) body.get("lines")).add(line);
            } else {
                if (!plan.limit().counted()) head.put(plan.limit().field(), chosen.quantity());
                singles.add(head);
            }
        }
        List<ObjectNode> all = new ArrayList<>(bodies.values());
        all.addAll(singles);
        String shown = plan.target().fields().stream().filter(field -> field.type().equals("serial")).map(AppDefinitions.Field::name).findFirst().orElse(null);
        List<Map<String, Object>> made = new ArrayList<>();
        for (ObjectNode body : all) {
            Map<String, Object> row = records.createFrom(plan.target().key(), body, authentication, false);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", row.get("id")); item.put("name", shown == null ? "" : text(row.get(shown)));
            made.add(item);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("count", made.size()); out.put("lines", request.rows().size()); out.put("created", made); out.put("entity", plan.target().key()); out.put("title", plan.target().title());
        return out;
    }
}
