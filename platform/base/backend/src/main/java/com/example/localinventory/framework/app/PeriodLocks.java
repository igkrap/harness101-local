package com.example.localinventory.framework.app;

import java.time.YearMonth;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Period locks: a part that knows no business. A definition says which lock group its records belong to and the date they are dated by
 * ("lock": {"group": "수불", "date": "inboundDate"}); a group is locked month by month, in order, and only its newest locked month opens
 * again. A record dated in a locked month takes no registration, change, deletion or status action. Other parts ask it whether a day is
 * locked for a group (through) and hear when a month closes or opens (Closed / Reopened); it knows nothing of them.
 */
@RestController
public class PeriodLocks {
    private final JdbcTemplate jdbc;
    private final AppDefinitions definitions;
    private final org.springframework.context.ApplicationEventPublisher events;
    public PeriodLocks(JdbcTemplate jdbc, AppDefinitions definitions, org.springframework.context.ApplicationEventPublisher events) { this.jdbc = jdbc; this.definitions = definitions; this.events = events; }
    public record Close(String period, String note) {}
    /** Told to whoever keeps something per month (the quantity ledger keeps what was held): a group's month was closed / opened again. */
    public record Closed(String group, YearMonth month) {}
    public record Reopened(String group, YearMonth month) {}

    private static String said(YearMonth month) { return month.getYear() + "년 " + month.getMonthValue() + "월"; }
    private static String name(AppDefinitions.Definition definition) { return definition.title().replaceAll("\\s*(등록|관리|입력)$", ""); }

    /** The newest locked month of a group (2026-10), or null: every month up to it is locked. */
    public String through(String group) {
        return jdbc.queryForObject("SELECT MAX(period) FROM period_locks WHERE lock_group = ?", String.class, group);
    }
    /** The screens of a group (drafts too: a screen being checked before it is published may lock its group). */
    private List<AppDefinitions.Definition> screens(String group) {
        List<AppDefinitions.Definition> out = new ArrayList<>();
        for (AppDefinitions.Stored stored : definitions.all())
            if (stored.definition().lock() != null && stored.definition().lock().group().equals(group)) out.add(stored.definition());
        return out;
    }
    /** A record of a locked month stays as it is - and none is put into one. day: the record's date (before or after the change). */
    public void open(AppDefinitions.Definition definition, Object day, String word) {
        if (definition.lock() == null || day == null) return;
        String text = String.valueOf(day);
        if (text.length() < 7 || !text.matches("\\d{4}[-/]\\d{2}.*")) return;
        String through = through(definition.lock().group());
        if (through != null && text.substring(0, 7).replace('/', '-').compareTo(through) <= 0) {
            AppDefinitions.Field field = definition.field(definition.lock().date());
            throw new ResponseStatusException(HttpStatus.CONFLICT, definition.lock().group() + " 마감이 " + said(YearMonth.parse(through)) + "까지 되어 있어 " + name(definition) + " 자료를 "
                    + word + "할 수 없습니다 (" + (field == null ? "" : field.label() + " ") + text.substring(0, 10).replace('-', '/') + "). 「마감」 화면에서 그 달을 다시 열 수 있습니다.");
        }
    }

    // ---- the 마감 screen: one page per group

    /** Every group the definitions name, each with its months (from its first record to this month): locked or not, and how many records. */
    @GetMapping("/api/locks")
    public List<Map<String, Object>> groups() {
        Map<String, List<AppDefinitions.Definition>> groups = new LinkedHashMap<>();
        for (AppDefinitions.Stored stored : definitions.all())
            if (stored.status().equals("PUBLISHED") && stored.definition().lock() != null && !stored.definition().key().startsWith("trial_"))
                groups.computeIfAbsent(stored.definition().lock().group(), ignored -> new ArrayList<>()).add(stored.definition());
        YearMonth now = YearMonth.from(RecordController.today());
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map.Entry<String, List<AppDefinitions.Definition>> group : groups.entrySet()) {
            Map<String, Integer> counts = new LinkedHashMap<>();
            for (AppDefinitions.Definition screen : group.getValue()) {
                if (!RecordStore.keeps(screen)) continue;
                for (Map<String, Object> row : jdbc.queryForList("SELECT to_char(" + RecordStore.column(screen.lock().date()) + ", 'YYYY-MM') AS period, COUNT(*) AS n FROM "
                        + RecordStore.table(screen.key()) + " WHERE " + RecordStore.column(screen.lock().date()) + " IS NOT NULL GROUP BY 1"))
                    counts.merge((String) row.get("period"), ((Number) row.get("n")).intValue(), Integer::sum);
            }
            String through = through(group.getKey());
            YearMonth start = now;
            for (String period : counts.keySet()) if (YearMonth.parse(period).isBefore(start)) start = YearMonth.parse(period);
            if (through != null && YearMonth.parse(through).isBefore(start)) start = YearMonth.parse(through);
            Map<String, Map<String, Object>> locked = new LinkedHashMap<>();
            for (Map<String, Object> row : jdbc.queryForList("SELECT period, closed_by, closed_at, note FROM period_locks WHERE lock_group = ?", group.getKey())) locked.put(((String) row.get("period")).trim(), row);
            List<Map<String, Object>> months = new ArrayList<>();
            for (YearMonth at = now; !at.isBefore(start); at = at.minusMonths(1)) {
                Map<String, Object> month = new LinkedHashMap<>(), done = locked.get(at.toString());
                month.put("period", at.toString()); month.put("closed", done != null); month.put("records", counts.getOrDefault(at.toString(), 0));
                month.put("closedBy", done == null ? null : done.get("closed_by")); month.put("closedAt", done == null ? null : String.valueOf(done.get("closed_at")).replace(' ', 'T'));
                months.add(month);
            }
            Map<String, Object> thing = new LinkedHashMap<>();
            thing.put("group", group.getKey()); thing.put("screens", group.getValue().stream().map(AppDefinitions.Definition::title).toList());
            thing.put("keys", group.getValue().stream().map(AppDefinitions.Definition::key).toList()); thing.put("through", through); thing.put("months", months);
            out.add(thing);
        }
        return out;
    }

    private static YearMonth month(String period) {
        if (period == null || !period.trim().matches("\\d{4}-(0[1-9]|1[0-2])")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "달은 2026-10 같은 모양으로 적습니다.");
        return YearMonth.parse(period.trim());
    }
    private void known(String group) {
        if (screens(group).isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "그런 마감 묶음이 없습니다: " + group);
    }

    /** Lock a month: the one after the group's newest locked month (the first time: any month up to this one - all before it lock with it). */
    @PostMapping("/api/locks/{group}")
    @Transactional
    public List<Map<String, Object>> close(@PathVariable String group, @RequestBody Close request, Authentication authentication) {
        known(group);
        YearMonth month = month(request.period()), now = YearMonth.from(RecordController.today());
        if (month.isAfter(now)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "아직 오지 않은 달은 마감할 수 없습니다.");
        String through = through(group);
        if (through != null && !month.equals(YearMonth.parse(through).plusMonths(1)))
            throw new ResponseStatusException(HttpStatus.CONFLICT, !month.isAfter(YearMonth.parse(through)) ? said(month) + "은 이미 마감되어 있습니다."
                    : "마감은 달 순서대로 합니다. 먼저 " + said(YearMonth.parse(through).plusMonths(1)) + "을 마감하세요.");
        String note = request.note() == null ? null : request.note().trim();
        jdbc.update("INSERT INTO period_locks (lock_group, period, closed_by, note) VALUES (?, ?, ?, ?)", group, month.toString(), authentication.getName(), note == null || note.isEmpty() ? null : note);
        events.publishEvent(new Closed(group, month));       // whoever keeps something per month keeps it now (in this same transaction)
        return groups();
    }

    /** Open the group's newest locked month again (only that one). */
    @DeleteMapping("/api/locks/{group}/{period}")
    @Transactional
    public List<Map<String, Object>> reopen(@PathVariable String group, @PathVariable String period) {
        known(group);
        YearMonth month = month(period);
        String through = through(group);
        if (through == null || !month.equals(YearMonth.parse(through)))
            throw new ResponseStatusException(HttpStatus.CONFLICT, through == null ? "마감된 달이 없습니다." : "가장 최근에 마감한 " + said(YearMonth.parse(through)) + "만 다시 열 수 있습니다.");
        events.publishEvent(new Reopened(group, month));
        jdbc.update("DELETE FROM period_locks WHERE lock_group = ? AND period = ?", group, month.toString());
        return groups();
    }
}
