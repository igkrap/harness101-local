package com.example.localinventory.framework.app;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

/**
 * Records of an entity as choices for other screens (the customer to pick on an order, its name in a list).
 * Any signed-in person may read them: permission is per screen, and a person who may enter orders must be able to
 * pick a customer without being given the customer screen. Read only, no lines, published entities only.
 */
@RestController
public class LookupController {
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final RecordStore store;
    public LookupController(AppDefinitions definitions, JdbcTemplate jdbc, RecordStore store) { this.definitions = definitions; this.jdbc = jdbc; this.store = store; }

    /**
     * The first records (1,000 unless _limit says otherwise, at most 5,000). q narrows them to those whose text fields hold it
     * (a code, a name ...); ids asks for exactly those records. X-Total-Count tells how many match in all, so a screen
     * knows when it holds only a part and must ask again with q.
     */
    /** The lines of a master with details, to choose one (a step of an item's routing): only those of records whose `field` is `value`; or by ids. */
    @GetMapping("/api/lookup/{entity}/lines")
    public List<Map<String, Object>> lines(@PathVariable String entity, @org.springframework.web.bind.annotation.RequestParam(required = false) String field,
                                           @org.springframework.web.bind.annotation.RequestParam(required = false) String value, @org.springframework.web.bind.annotation.RequestParam(required = false) String ids) {
        AppDefinitions.Stored stored = definitions.find(entity);
        if (stored == null || stored.definition().lines() == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "줄을 고를 수 있는 자료가 아닙니다: " + entity);
        java.util.List<Long> wanted = new java.util.ArrayList<>();
        if (ids != null) for (String part : ids.split(",")) if (part.trim().matches("\\d{1,15}")) wanted.add(Long.parseLong(part.trim()));
        return store.lineRows(stored.definition(), field, value, wanted);
    }

    @GetMapping("/api/lookup/{entity}")
    public List<Map<String, Object>> list(@PathVariable String entity, @org.springframework.web.bind.annotation.RequestParam(required = false) String q,
                                          @org.springframework.web.bind.annotation.RequestParam(required = false) String ids,
                                          @org.springframework.web.bind.annotation.RequestParam(name = "_limit", defaultValue = "1000") int limit,
                                          jakarta.servlet.http.HttpServletResponse response) {
        AppDefinitions.Stored stored = definitions.find(entity);
        if (stored == null || stored.definition().fields().isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "고를 수 있는 자료가 아닙니다: " + entity);
        StringBuilder where = new StringBuilder(" FROM " + store.source(entity) + " app_records WHERE entity_key = ?");
        java.util.List<Object> args = new java.util.ArrayList<>(List.of(entity));
        if (ids != null && !ids.isBlank()) {
            java.util.List<Long> wanted = new java.util.ArrayList<>();
            for (String part : ids.split(",")) if (part.trim().matches("\\d{1,15}")) wanted.add(Long.parseLong(part.trim()));
            where.append(" AND id = ANY(?)");
            args.add(wanted.toArray(new Long[0]));
        }
        if (q != null && !q.isBlank()) {
            java.util.List<String> texts = stored.definition().fields().stream().filter(AppDefinitions.Field::wordy).map(AppDefinitions.Field::name).toList();
            if (!texts.isEmpty()) {
                where.append(" AND (").append(String.join(" OR ", java.util.Collections.nCopies(texts.size(), "LOWER(data->>?) LIKE ?"))).append(")");
                for (String name : texts) { args.add(name); args.add("%" + q.trim().toLowerCase() + "%"); }
            }
        }
        Long total = jdbc.queryForObject("SELECT COUNT(*)" + where, Long.class, args.toArray());
        response.setHeader("X-Total-Count", String.valueOf(total == null ? 0 : total));
        return jdbc.query("SELECT id, data::text AS data, status" + where + " ORDER BY id LIMIT " + Math.max(1, Math.min(5000, limit)), (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("id", row.getLong("id"));
            Map<String, Object> data = mapper.readValue(row.getString("data"), new tools.jackson.core.type.TypeReference<LinkedHashMap<String, Object>>() {});
            for (AppDefinitions.LineSet set : stored.definition().lineSets()) data.remove(set.name());
            out.putAll(data);
            if (row.getString("status") != null) out.put("status", row.getString("status"));
            return out;
        }, args.toArray());
    }
}
