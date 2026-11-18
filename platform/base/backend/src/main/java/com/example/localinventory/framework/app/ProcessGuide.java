package com.example.localinventory.framework.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The system's processes in words, read off the definitions themselves: the flows of work (which screen leads to which and how - a
 * take-over screen, something made by itself, master data expanded, a quantity limit), the layers of master data, and every screen
 * in sentences (what it holds, what it refuses, what follows from it). People read it as the 업무 안내서; the model building screens
 * reads the same text, so what it is told and what people see never differ. Nothing here is written by hand: change a screen and
 * the guide changes with it.
 */
@RestController
public class ProcessGuide {
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    public ProcessGuide(AppDefinitions definitions, JdbcTemplate jdbc) { this.definitions = definitions; this.jdbc = jdbc; }

    /** Rules every screen has, whatever its definition says. */
    static final List<String> COMMON = List.of(
            "다른 화면의 자료가 가리키고 있는 자료는 지울 수 없다 (먼저 그쪽을 지우거나 바꿔야 한다).",
            "모든 등록·수정·삭제·상태 처리는 그 화면의 이력에 남는다 (자료마다 이력 버튼으로 본다).");

    private Map<String, AppDefinitions.Definition> known;
    private Map<String, String> codeNames;

    @GetMapping("/api/meta/process")
    public synchronized Map<String, Object> guide() {
        known = new LinkedHashMap<>();
        for (AppDefinitions.Stored stored : definitions.all())
            if (stored.status().equals("PUBLISHED") && !stored.definition().key().startsWith("trial_")) known.put(stored.definition().key(), stored.definition());
        codeNames = new LinkedHashMap<>();
        for (Map<String, Object> row : jdbc.queryForList("SELECT group_code, group_name FROM sys_code_groups")) codeNames.put((String) row.get("group_code"), (String) row.get("group_name"));
        Map<String, String> programs = new LinkedHashMap<>();
        for (AppDefinitions.Stored stored : definitions.all()) programs.put(stored.definition().key(), stored.programCode());

        // ---- the steps between screens, earlier → later, each with how it happens
        Map<String, Map<String, List<String>>> steps = new LinkedHashMap<>();
        for (AppDefinitions.Definition d : known.values()) {
            if (d.take() != null && known.containsKey(d.take().from()) && known.containsKey(d.take().entity()))
                step(steps, d.take().from(), d.take().entity(), "「" + d.title() + "」 화면에서 " + q(d.take().from()) + " 중 아직 넘기지 않은 것을 골라 수량을 적어 한꺼번에 넘긴다 (손으로)"
                        + (d.take().statuses().isEmpty() ? "" : " - " + statusWords(d.take().from(), d.take().statuses()) + " 상태인 건만"));
            for (AppDefinitions.Effect effect : d.effects()) {
                if (effect.create() != null && known.containsKey(effect.create().entity()))
                    step(steps, d.key(), effect.create().entity(), q(d.key()) + "을(를) " + when(d, effect.on()) + " " + q(effect.create().entity()) + "이(가) 저절로 만들어진다");
                if (effect.expand() != null && known.containsKey(effect.expand().into()))
                    step(steps, d.key(), effect.expand().into(), expandWords(d, effect));
            }
            for (AppDefinitions.Limit limit : d.limits())
                if (!limit.entity().equals(d.key()) && known.containsKey(limit.entity()) && isWork(limit.entity()))
                    step(steps, limit.entity(), d.key(), q(d.key()) + "은(는) " + q(limit.entity()) + "을(를) 가리키고, " + (limit.once() ? q(limit.entity()) + " 한 건에 한 번만 이어진다" : limit.counted() ? "건수가 " + q(limit.entity()) + "의 " + label(known.get(limit.entity()), limit.entityField()) + "을(를) 넘을 수 없다"
                            : label(d, limit.field()) + " 합이 " + q(limit.entity()) + "의 " + label(known.get(limit.entity()), limit.entityField()) + "을(를) 넘을 수 없다"));
        }
        // what a later screen does back to an earlier one
        Map<String, Map<String, List<String>>> back = new LinkedHashMap<>();
        for (AppDefinitions.Definition d : known.values())
            for (AppDefinitions.Effect effect : d.effects()) {
                if (effect.act() != null) {
                    AppDefinitions.Field via = d.field(effect.act().via());
                    if (via != null && via.ref() != null && known.containsKey(via.ref().entity()))
                        step(back, via.ref().entity(), d.key(), q(d.key()) + "을(를) " + when(d, effect.on()) + " 가리키는 " + q(via.ref().entity()) + "이(가) "
                                + done(actionWord(via.ref().entity(), effect.act().action())));
                }
                if (effect.cascade() != null && known.containsKey(effect.cascade().entity()))
                    step(back, d.key(), effect.cascade().entity(), q(d.key()) + "을(를) " + when(d, effect.on()) + " 그것을 가리키는 " + q(effect.cascade().entity()) + "도 "
                            + done(actionWord(effect.cascade().entity(), effect.cascade().action())));
                if (effect.fill() != null && known.containsKey(effect.fill().entity()))
                    step(back, effect.fill().entity(), d.key(), q(d.key()) + " 수량이 " + q(effect.fill().entity()) + "의 수량을 다 채우면 " + q(effect.fill().entity()) + "이(가) "
                            + done(actionWord(effect.fill().entity(), effect.fill().action())));
            }

        // ---- the flows: every path from a screen nothing leads to, to one that leads nowhere
        Set<String> led = new LinkedHashSet<>();
        steps.values().forEach(to -> led.addAll(to.keySet()));
        List<List<String>> paths = new ArrayList<>();
        for (String start : steps.keySet()) if (!led.contains(start)) walk(steps, List.of(start), paths);
        List<Map<String, Object>> flows = new ArrayList<>();
        Map<String, List<String>> flowOf = new LinkedHashMap<>();
        for (List<String> path : paths) {
            String name = String.join(" → ", path.stream().map(this::title).toList());
            List<Map<String, Object>> parts = new ArrayList<>();
            for (int index = 0; index + 1 < path.size(); index++) {
                String from = path.get(index), to = path.get(index + 1);
                List<String> how = new ArrayList<>(steps.get(from).get(to));
                how.addAll(back.getOrDefault(from, Map.of()).getOrDefault(to, List.of()));
                parts.add(Map.of("from", from, "to", to, "how", how));
            }
            // the flow's screens in the order work goes through them: each stage, the screens that register or handle it, then the take-over
            // screen that leads on to the next stage
            List<String> screens = new ArrayList<>();
            for (int index = 0; index < path.size(); index++) {
                String stage = path.get(index);
                screens.add(stage);
                for (AppDefinitions.Definition other : known.values())
                    if (other.over() != null && other.over().entity().equals(stage)) screens.add(other.key());
                if (index + 1 < path.size())
                    for (AppDefinitions.Definition other : known.values())
                        if (other.take() != null && other.take().from().equals(stage) && other.take().entity().equals(path.get(index + 1))) screens.add(other.key());
            }
            Map<String, Object> flow = new LinkedHashMap<>();
            flow.put("name", name); flow.put("title", noun(path.get(0)) + " - " + noun(path.get(path.size() - 1)));
            flow.put("stages", path); flow.put("screens", screens); flow.put("steps", parts);
            flows.add(flow);
            for (String key : path) flowOf.computeIfAbsent(key, ignored -> new ArrayList<>()).add(name);
        }

        // ---- master data by layer: a master that points at no other master is layer 1, one that combines layer-1 masters is layer 2 ...
        Map<String, Integer> layers = new LinkedHashMap<>();
        for (String key : known.keySet()) if (kind(key, flowOf).equals("기준 정보")) layer(key, layers, flowOf, new LinkedHashSet<>());

        // ---- every screen in sentences
        List<Map<String, Object>> screens = new ArrayList<>();
        for (AppDefinitions.Definition d : known.values()) {
            Map<String, Object> screen = new LinkedHashMap<>();
            screen.put("key", d.key()); screen.put("title", d.title()); screen.put("programCode", programs.get(d.key()));
            String kind = kind(d.key(), flowOf);
            screen.put("kind", kind);
            if (layers.containsKey(d.key())) screen.put("layer", layers.get(d.key()));
            screen.put("flows", flowOf.getOrDefault(d.key(), List.of()));
            screen.put("fields", d.fields().stream().map(field -> fieldWords(d, field)).toList());
            List<Map<String, Object>> lineTables = new ArrayList<>();
            for (AppDefinitions.LineSet set : d.lineSets())
                lineTables.add(Map.of("label", set.label() == null ? "명세" : set.label(), "fields", set.fields().stream().map(field -> fieldWords(d, field)).toList()));
            screen.put("lines", lineTables);
            screen.put("sentences", sentences(d));
            List<String> users = new ArrayList<>();
            for (AppDefinitions.Definition other : known.values())
                if (!other.key().equals(d.key()) && ProcessGraph.dependsOn(other, known.keySet()).stream().anyMatch(on -> d.key().equals(on.get("key")))) users.add(other.title());
            screen.put("usedBy", users);
            screens.add(screen);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        List<String> common = new ArrayList<>(COMMON);        // the ledger's rule only where something moves quantities
        if (known.values().stream().anyMatch(definition -> definition.ledger() != null))
            common.add("수량이 나가는 화면은 그 위치에 남은 수량이 모자라면 저장되지 않는다 (먼저 들어온 묶음부터 나간다).");
        out.put("flows", flows); out.put("screens", screens); out.put("common", common);
        out.put("text", text(flows, screens, common));
        return out;
    }

    // ---- words

    private String title(String key) { AppDefinitions.Definition d = known.get(key); return d == null ? key : d.title(); }
    /** A record of a screen as a noun: the screen's name without 등록/관리/입력 (「작업지시」, not 「작업지시 등록」). */
    private String noun(String key) { return title(key).replaceAll("\\s*(등록|관리|입력)$", ""); }
    private String q(String key) { return "「" + title(key).replaceAll("\\s*(등록|관리|입력)$", "") + "」"; }
    private static String label(AppDefinitions.Definition d, String name) {
        if (d == null || name == null) return String.valueOf(name);
        for (AppDefinitions.Field field : d.fields()) if (field.name().equals(name)) return "「" + field.label() + "」";
        for (AppDefinitions.LineSet set : d.lineSets()) for (AppDefinitions.Field field : set.fields()) if (field.name().equals(name)) return "「" + field.label() + "」";
        return name;
    }
    private String when(AppDefinitions.Definition d, String on) { return "create".equals(on) ? "등록하면" : actionWord(d.key(), on) + "하면"; }
    private String actionWord(String key, String action) {
        AppDefinitions.Definition d = known.get(key);
        if (d != null && d.status() != null)
            for (AppDefinitions.Action candidate : d.status().actions()) if (candidate.name().equals(action)) return "「" + candidate.label() + "」";
        return action;
    }
    /** 「확정」 처리된다, but 「출고 완료 처리」된다. */
    private static String done(String word) { return word.endsWith("처리」") ? word + "된다" : word + " 처리된다"; }
    private String statusWords(String key, List<String> codes) {
        AppDefinitions.Definition d = known.get(key);
        List<String> out = new ArrayList<>();
        for (String code : codes) out.add(d == null || d.status() == null ? code : "「" + d.status().label(code) + "」");
        return String.join("·", out);
    }
    private String expandWords(AppDefinitions.Definition d, AppDefinitions.Effect effect) {
        AppDefinitions.Expand expand = effect.expand();
        AppDefinitions.Definition master = known.get(expand.from());
        String by = String.join(", ", expand.match().entrySet().stream().map(entry -> label(d, entry.getValue()) + "이(가) " + label(master, entry.getKey())).toList());
        return q(d.key()) + "을(를) " + when(d, effect.on()) + " 기준 정보 " + q(expand.from()) + "에서 " + by + "인 것을 찾아" + (expand.at() != null ? " (" + label(d, expand.at()) + "에 유효한 것)" : master != null && master.effective() != null ? " (등록하는 날 유효한 것)" : "")
                + " " + (master != null && master.lines() != null ? "그 줄마다" : "한 건마다") + " " + q(expand.into()) + "을(를) 한 건씩 만든다"
                + (expand.quantityInto() != null ? " - 수량은 " + label(master, expand.quantityLine()) + (expand.quantityTimes() != null ? " × " + label(d, expand.quantityTimes()) : "") : "")
                + ". 만든 뒤에 기준 정보가 바뀌어도 이미 만든 것은 그대로다";
    }

    private Map<String, Object> fieldWords(AppDefinitions.Definition d, AppDefinitions.Field field) {
        List<String> words = new ArrayList<>();
        switch (field.type()) {
            case "user" -> words.add("등록한 사람(저절로)");
            case "serial" -> words.add("자동 번호" + (field.prefix() == null ? "" : " (" + field.prefix() + "-…)"));
            case "ref" -> words.add((field.ref() != null ? q(field.ref().entity()) : "다른 화면") + (field.ref() != null && field.ref().line() ? "의 줄" : "") + "에서 고름");
            case "code" -> words.add("공통 코드 「" + codeNames.getOrDefault(field.codeGroup(), field.codeGroup()) + "」에서 고름");
            case "number" -> words.add("숫자" + (field.decimals() == null ? "" : field.decimals() == 0 ? " (정수)" : " (소수 " + field.decimals() + "자리)")
                    + (field.min() != null || field.max() != null ? " " + (field.min() == null ? "" : fmt(field.min())) + "~" + (field.max() == null ? "" : fmt(field.max())) : ""));
            case "date" -> words.add("날짜");
            case "time" -> words.add("시각");
            case "yesno" -> words.add("예/아니오");
            case "memo" -> words.add("긴 글");
            default -> words.add("글자");
        }
        if (field.required()) words.add("필수");
        if (field.unique()) words.add("중복 불가");
        if (field.formula() != null) words.add("계산: " + field.formula());
        if (field.sum() != null) words.add("줄의 " + label(d, field.sum()) + " 합계");
        if (field.fill() != null && !field.fill().isEmpty()) words.add("고르면 " + String.join(", ", field.fill().keySet().stream().map(name -> label(d, name)).toList()) + "이(가) 채워짐");
        for (Object[] pair : new Object[][] {{field.showWhen(), "만 보임"}, {field.requiredWhen(), " 필수"}, {field.lockWhen(), " 고칠 수 없음"}}) {
            AppDefinitions.Condition condition = (AppDefinitions.Condition) pair[0];
            if (condition == null) continue;
            String other = label(d, condition.field());
            boolean empty = condition.is().size() == 1 && condition.is().get(0).isEmpty();
            String phrase = empty ? (condition.not() ? other + "을(를) 고르거나 적으면" : other + "이(가) 비어 있을 때")
                    : other + "이(가) " + String.join("·", condition.is()) + (condition.not() ? "이(가) 아닐 때" : "일 때");
            String word = (String) pair[1];
            if (word.startsWith("만") && phrase.endsWith("면")) word = " 보임";
            words.add(phrase + word);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("label", field.label()); out.put("words", String.join(", ", words));
        return out;
    }
    private static String fmt(Double value) { return value % 1 == 0 ? String.valueOf(value.longValue()) : String.valueOf(value); }

    private List<String> sentences(AppDefinitions.Definition d) {
        List<String> out = new ArrayList<>();
        if (d.take() != null) {
            AppDefinitions.Take take = d.take();
            out.add(q(take.from()) + " 중 아직 다 넘기지 않은 건을 목록으로 보여 준다" + (take.statuses().isEmpty() ? "" : " (" + statusWords(take.from(), take.statuses()) + " 상태인 건만)")
                    + ". 줄을 골라 이번 수량" + (take.ask() == null || take.ask().isEmpty() ? "" : "과 " + String.join(", ", take.ask().stream().map(name -> label(known.get(take.entity()), name)).toList()))
                    + "을(를) 적고 저장하면 고른 줄마다 " + q(take.entity()) + "이(가) 만들어진다. 편집 패널 없이 표에서 처리한다.");
        }
        if (d.ledgerView() != null) out.add((d.ledgerView().thing() == null ? "수량 원장 전체" : q(d.ledgerView().thing()) + "의 수량") + "을 보여 주기만 하는 화면이다: "
                + Map.of("all", "현재 수량, 묶음, 들고 난 내역", "balance", "현재 수량", "lots", "묶음", "moves", "들고 난 내역").getOrDefault(d.ledgerView().show(), d.ledgerView().show()) + ".");
        if (d.summary() != null) out.add(q(d.summary().entity()) + "의 자료를 모아 합계·건수를 보여 주는 집계 화면이다.");
        if (d.over() != null && d.over().create() && d.over().actions().isEmpty() && !d.over().edit())
            out.add(q(d.over().entity()) + "을(를) 새로 등록만 하는 화면이다" + (known.get(d.over().entity()) != null && known.get(d.over().entity()).follows() != null ? " (기타: 앞 단계 없이 등록)" : "") + ". 고치기·취소·마감은 그 자료의 관리 화면에서 한다.");
        else if (d.over() != null) out.add(q(d.over().entity()) + "의 자료를 " + (d.over().statuses().isEmpty() ? "" : statusWords(d.over().entity(), d.over().statuses()) + " 상태인 것만 ") + "열어 처리하는 화면이다"
                + (d.over().create() ? " (새로 등록도 한다)" : "") + ".");
        if (d.calendar() != null) out.add(q(d.calendar().entity()) + "의 자료를 달력에 보여 준다.");
        if (d.tree() != null) out.add(q(d.tree().entity()) + "의 자료를 위아래 관계(트리)로 보여 준다.");
        if (d.status() != null) {
            out.add("상태: " + String.join(" → ", d.status().values().stream().map(value -> "「" + value.label() + "」").toList()) + " (처음은 「" + d.status().label(d.status().initial()) + "」).");
            for (AppDefinitions.Action action : d.status().actions())
                out.add("「" + action.label() + "」: " + statusWords(d.key(), action.from()) + "에서 「" + d.status().label(action.to()) + "」(으)로." + (action.separate() ? " 이 일을 하는 화면에서만 한다." : ""));
            if (!d.status().locked().isEmpty()) out.add(statusWords(d.key(), d.status().locked()) + " 상태에서는 고치거나 지울 수 없다.");
        }
        if (d.lock() != null) out.add(d.lock().group() + " 마감에 속한다: " + label(d, d.lock().date()) + "이(가) 마감된 달인 자료는 등록·수정·삭제·상태 처리를 할 수 없다.");
        for (AppDefinitions.Lookup lookup : d.lookups())
            out.add(String.join(", ", lookup.set().keySet().stream().map(name -> label(d, name)).toList()) + "은(는) 비어 있으면 " + q(lookup.from()) + "에서 "
                    + String.join("·", lookup.match().values().stream().map(name -> label(d, name)).toList()) + "이(가) 같은 것"
                    + (lookup.at() != null ? "(" + label(d, lookup.at()) + " 기준)" : "") + "을 찾아 채운다.");
        if (d.dataOnly()) out.add("화면 없이 데이터로만 있다: 다른 업무에서 저절로 만들어지고 바뀌며, 사람이 직접 등록하거나 고치지 않는다.");
        if (d.follows() != null) out.add(label(d, d.follows()) + "이(가) 가리키는 앞 단계를 이어받아서만 생긴다 (이어받기 화면에서 등록, 이 화면에서는 신규 등록 없음). 앞 단계 없이 등록하는 것은 기타 화면에서 한다.");
        if (d.status() != null && d.status().closed() != null && !d.status().closed().isEmpty())
            out.add(statusWords(d.key(), d.status().closed()) + " 상태가 되면 끝난 것이다: 다음 단계로 더 이어지지 않는다 (남은 것은 이어받기 목록에서 빠지고, 새로 이어서 등록할 수 없다).");
        if (d.effective() != null) out.add("적용 기간(" + label(d, d.effective().from()) + " ~ " + (d.effective().to() == null ? "계속" : label(d, d.effective().to())) + ")이 있다"
                + (d.effective().by().isEmpty() ? "." : ". " + String.join("·", d.effective().by().stream().map(name -> label(d, name)).toList()) + "이(가) 같은 것끼리 기간이 겹칠 수 없다."));
        for (AppDefinitions.NoOverlap span : d.noOverlap() == null ? List.<AppDefinitions.NoOverlap>of() : d.noOverlap())
            out.add(span.message() != null ? span.message() : (span.by().isEmpty() ? "" : String.join("·", span.by().stream().map(name -> label(d, name)).toList()) + "이(가) 같은 것끼리 ")
                    + label(d, span.from()) + "~" + label(d, span.to()) + "이(가) 겹칠 수 없다.");
        for (List<String> group : d.uniqueBy() == null ? List.<List<String>>of() : d.uniqueBy())
            out.add(String.join("·", group.stream().map(name -> label(d, name)).toList()) + "이(가) 같은 자료는 하나만 등록할 수 있다.");
        if (d.noCycle() != null) out.add(label(d, d.noCycle().child()) + "은(는) " + label(d, d.noCycle().parent()) + " 자신이거나, 돌고 돌아 다시 그것을 품게 될 수 없다 (순환 금지).");
        for (AppDefinitions.Check check : d.checks()) out.add(check.message());
        for (AppDefinitions.Limit limit : d.limits()) out.add(limit.message() == null || limit.message().isBlank()
                ? limit.once() ? q(limit.entity()) + " 한 건에 한 번만 이어진다." : limit.counted() ? "건수가 " + q(limit.entity()) + "의 " + label(known.get(limit.entity()), limit.entityField()) + "을(를) 넘을 수 없다." : label(d, limit.field()) + " 합이 " + q(limit.entity()) + "의 " + label(known.get(limit.entity()), limit.entityField()) + "을(를) 넘을 수 없다." : limit.message());
        for (AppDefinitions.Rule rule : d.rules()) if (rule.message() != null) out.add(rule.message());
        if (d.ledger() != null) {
            AppDefinitions.Ledger ledger = d.ledger();
            String place = label(d, ledger.place());
            out.add(switch (ledger.direction()) {
                case "in" -> "저장하면 " + place + "에 재고가 들어온다. LOT 이 생기고" + (ledger.unitCost() == null ? "" : " 단가는 " + label(d, ledger.unitCost())) + (ledger.lot() == null ? "" : ", LOT 번호는 " + label(d, ledger.lot()) + "에 적은 것") + ".";
                case "out" -> "저장하면 " + place + "에서 재고가 나간다 (오래된 LOT 부터" + (ledger.lot() == null ? "" : ", " + label(d, ledger.lot()) + "을(를) 적으면 그 LOT 에서") + "). 재고가 모자라면 저장되지 않는다.";
                case "move" -> "저장하면 " + place + "에서 " + label(d, ledger.toPlace()) + "(으)로 재고가 옮겨진다 (LOT 번호와 단가가 따라간다).";
                default -> "센 수량으로 " + place + "의 장부를 맞추고, 차이는 수불 내역에 들어오거나 나간 것으로 남는다.";
            } + " 수불 날짜는 " + (ledger.date() == null ? "등록한 날" : label(d, ledger.date())) + "이다.");
        }
        for (AppDefinitions.Effect effect : d.effects()) {
            if (effect.create() != null) out.add(when(d, effect.on()) + " " + q(effect.create().entity()) + "이(가) 저절로 만들어진다.");
            if (effect.expand() != null) out.add(expandWords(d, effect) + ".");
            if (effect.act() != null) {
                AppDefinitions.Field via = d.field(effect.act().via());
                if (via != null && via.ref() != null) out.add(when(d, effect.on()) + " " + label(d, via.name()) + "이(가) 가리키는 " + q(via.ref().entity()) + "이(가) " + done(actionWord(via.ref().entity(), effect.act().action())) + ".");
            }
            if (effect.cascade() != null) out.add(when(d, effect.on()) + " 이 자료를 가리키는 " + q(effect.cascade().entity()) + "도 " + done(actionWord(effect.cascade().entity(), effect.cascade().action())) + " (아래로 전파).");
            if (effect.fill() != null) out.add("수량이 " + q(effect.fill().entity()) + "의 수량을 다 채우면 그것이 " + done(actionWord(effect.fill().entity(), effect.fill().action())) + ".");
        }
        return out;
    }

    // ---- shapes

    private void step(Map<String, Map<String, List<String>>> steps, String from, String to, String how) {
        steps.computeIfAbsent(from, ignored -> new LinkedHashMap<>()).computeIfAbsent(to, ignored -> new ArrayList<>()).add(how);
    }
    private void walk(Map<String, Map<String, List<String>>> steps, List<String> path, List<List<String>> out) {
        if (out.size() >= 50) return;
        Map<String, List<String>> next = steps.getOrDefault(path.get(path.size() - 1), Map.of());
        boolean further = false;
        for (String to : next.keySet()) {
            if (path.contains(to)) continue;
            List<String> longer = new ArrayList<>(path); longer.add(to);
            walk(steps, longer, out); further = true;
        }
        if (!further && path.size() > 1) out.add(path);
    }
    /** Work moves along (a status, stock, something that follows from it, a limit against an earlier stage, a take-over); master data is pointed at. */
    private boolean isWork(String key) {
        AppDefinitions.Definition d = known.get(key);
        return d != null && (d.status() != null || d.ledger() != null || !d.effects().isEmpty() || !d.limits().isEmpty() || d.take() != null);
    }
    private String kind(String key, Map<String, List<String>> flowOf) {
        AppDefinitions.Definition d = known.get(key);
        if (d.dataOnly()) return "데이터";
        if (d.take() != null) return "이어받기";
        if (d.ledgerView() != null) return "원장 보기";
        if (d.summary() != null) return "집계";
        if (d.dashboard() != null) return "현황판";
        if (d.over() != null) return "업무 처리";
        if (d.calendar() != null) return "달력";
        if (d.tree() != null) return "트리";
        if (flowOf.containsKey(key) || isWork(key)) return "업무";
        return "기준 정보";
    }
    private int layer(String key, Map<String, Integer> layers, Map<String, List<String>> flowOf, Set<String> seen) {
        if (layers.containsKey(key)) return layers.get(key);
        if (!seen.add(key)) return 1;
        int deepest = 0;
        for (Map<String, Object> on : ProcessGraph.dependsOn(known.get(key), known.keySet()))
            if (kind((String) on.get("key"), flowOf).equals("기준 정보"))
                deepest = Math.max(deepest, layer((String) on.get("key"), layers, flowOf, seen));
        layers.put(key, deepest + 1);
        return deepest + 1;
    }

    @SuppressWarnings("unchecked")
    private String text(List<Map<String, Object>> flows, List<Map<String, Object>> screens, List<String> common) {
        StringBuilder out = new StringBuilder();
        out.append("[업무 흐름]\n");
        if (flows.isEmpty()) out.append("(화면끼리 이어진 흐름이 아직 없다)\n");
        int number = 0;
        for (Map<String, Object> flow : flows) {
            out.append(++number).append(". ").append(flow.get("title")).append(" (").append(flow.get("name")).append(")\n");
            for (Map<String, Object> step : (List<Map<String, Object>>) flow.get("steps"))
                for (String how : (List<String>) step.get("how")) out.append("   - ").append(title((String) step.get("from"))).append(" → ").append(title((String) step.get("to"))).append(": ").append(how).append('\n');
        }
        out.append("\n[기준 정보]\n");
        screens.stream().filter(screen -> screen.containsKey("layer")).sorted((a, b) -> Integer.compare((Integer) a.get("layer"), (Integer) b.get("layer")))
                .forEach(screen -> out.append("- Layer ").append(screen.get("layer")).append(": ").append(screen.get("title"))
                        .append(((List<String>) screen.get("usedBy")).isEmpty() ? "" : " (쓰는 화면: " + String.join(", ", (List<String>) screen.get("usedBy")) + ")").append('\n'));
        out.append("\n[화면별]\n");
        for (Map<String, Object> screen : screens) {
            out.append("■ ").append(screen.get("title")).append(" (").append(screen.get("key")).append(", ").append(screen.get("kind")).append(")\n");
            List<Map<String, Object>> fields = (List<Map<String, Object>>) screen.get("fields");
            if (!fields.isEmpty()) out.append("   항목: ").append(String.join("; ", fields.stream().map(field -> field.get("label") + "(" + field.get("words") + ")").toList())).append('\n');
            for (Map<String, Object> lines : (List<Map<String, Object>>) screen.get("lines"))
                out.append("   줄 표 ").append(lines.get("label")).append(": ").append(String.join("; ", ((List<Map<String, Object>>) lines.get("fields")).stream().map(field -> field.get("label") + "(" + field.get("words") + ")").toList())).append('\n');
            for (String sentence : (List<String>) screen.get("sentences")) out.append("   - ").append(sentence).append('\n');
            List<String> in = (List<String>) screen.get("flows");
            if (!in.isEmpty()) out.append("   - 속한 흐름: ").append(String.join(" / ", in)).append('\n');
        }
        out.append("\n[모든 화면에 걸리는 규칙]\n");
        for (String rule : common) out.append("- ").append(rule).append('\n');
        return out.toString();
    }
}
