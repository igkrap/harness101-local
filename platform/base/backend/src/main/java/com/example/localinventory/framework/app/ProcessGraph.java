package com.example.localinventory.framework.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The screens as one graph, read off the definitions (nothing written by hand): a node is an entity that keeps records, with its
 * states and the steps that move a record between them (which work screen, which action); an edge goes from an earlier entity to a
 * later one, with how the later records come of the earlier ones:
 *   from     made from the earlier records, each once (definition.from)
 *   take     taken over in quantities (a take-over screen on a limit)
 *   limit    pointing at the earlier record within a quantity (no take-over screen)
 *   expand   made by themselves from master data when the earlier one is registered
 *   create   made by themselves when the earlier one is registered or moved on
 *   choose   the earlier entity is only chosen from (master data)
 * Definitions write only the earlier side; next is worked out here. Branches and joins are just more edges.
 */
@RestController
public class ProcessGraph {
    private final AppDefinitions definitions;
    public ProcessGraph(AppDefinitions definitions) { this.definitions = definitions; }

    @GetMapping("/api/meta/graph")
    public Map<String, Object> graph(@RequestParam(defaultValue = "false") boolean drafts) {
        Map<String, AppDefinitions.Definition> known = new LinkedHashMap<>();
        for (AppDefinitions.Stored stored : definitions.all())
            if ((drafts || stored.status().equals("PUBLISHED")) && !stored.definition().key().startsWith("trial_")) known.put(stored.definition().key(), stored.definition());
        Map<String, Map<String, Object>> nodes = new LinkedHashMap<>();
        for (AppDefinitions.Definition d : known.values()) {
            if (!RecordStore.keeps(d)) continue;
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("key", d.key());
            node.put("title", d.title());
            List<Map<String, Object>> states = new ArrayList<>();
            if (d.status() != null)
                for (AppDefinitions.StatusValue value : d.status().values()) {
                    Map<String, Object> state = new LinkedHashMap<>();
                    state.put("code", value.code()); state.put("label", value.label());
                    state.put("initial", value.code().equals(d.status().initial())); state.put("closed", d.status().isClosed(value.code()));
                    states.add(state);
                }
            node.put("states", states);
            node.put("steps", new ArrayList<Map<String, Object>>());
            node.put("prev", new ArrayList<Map<String, Object>>());
            node.put("next", new ArrayList<Map<String, Object>>());
            nodes.put(d.key(), node);
        }
        // the steps of a record: its own actions, and the work screens that take some of them
        for (AppDefinitions.Definition d : known.values()) {
            if (!nodes.containsKey(d.key()) || d.status() == null) continue;
            for (AppDefinitions.Action action : d.status().actions()) {
                List<Map<String, Object>> screens = new ArrayList<>();
                for (AppDefinitions.Definition other : known.values())
                    if (other.over() != null && other.over().entity().equals(d.key()) && other.over().actions().contains(action.name()))
                        screens.add(Map.of("key", other.key(), "title", other.title()));
                Map<String, Object> step = new LinkedHashMap<>();
                step.put("action", action.name()); step.put("label", action.label()); step.put("from", action.from()); step.put("to", action.to());
                step.put("separate", action.separate()); step.put("screens", screens);
                steps(nodes.get(d.key())).add(step);
            }
        }
        List<Map<String, Object>> edges = new ArrayList<>();
        for (AppDefinitions.Definition d : known.values()) {
            if (!nodes.containsKey(d.key())) continue;
            java.util.Set<String> linked = new java.util.HashSet<>();
            if (d.from() != null) { edge(edges, nodes, d.from().entity(), d.key(), "from", d.from().pointer(), null); linked.add(d.from().entity()); }
            for (AppDefinitions.Limit limit : d.limits()) {
                if (linked.contains(limit.entity()) || !limit.entityBy().contains("id")) continue;
                String take = known.values().stream().filter(other -> other.take() != null && other.take().entity().equals(d.key()) && other.take().from().equals(limit.entity()))
                        .map(AppDefinitions.Definition::key).findFirst().orElse(null);
                edge(edges, nodes, limit.entity(), d.key(), take != null ? "take" : "limit", limit.by().get(limit.entityBy().indexOf("id")), take);
                linked.add(limit.entity());
            }
            for (AppDefinitions.Effect effect : d.effects()) {
                if (effect.expand() != null) edge(edges, nodes, d.key(), effect.expand().into(), "expand", null, null);
                if (effect.create() != null) edge(edges, nodes, d.key(), effect.create().entity(), "create", null, null);
            }
            for (AppDefinitions.Field field : d.fields())
                if (field.ref() != null && !linked.contains(field.ref().entity()) && !field.ref().entity().equals(d.key())) {
                    edge(edges, nodes, field.ref().entity(), d.key(), "choose", field.name(), null);
                    linked.add(field.ref().entity());
                }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("nodes", new ArrayList<>(nodes.values()));
        out.put("edges", edges);
        return out;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> steps(Map<String, Object> node) { return (List<Map<String, Object>>) node.get("steps"); }
    @SuppressWarnings("unchecked")
    private static void edge(List<Map<String, Object>> edges, Map<String, Map<String, Object>> nodes, String from, String to, String how, String pointer, String screen) {
        if (!nodes.containsKey(from) || !nodes.containsKey(to)) return;
        Map<String, Object> edge = new LinkedHashMap<>();
        edge.put("from", from); edge.put("to", to); edge.put("how", how);
        if (pointer != null) edge.put("pointer", pointer);
        if (screen != null) edge.put("screen", screen);
        edges.add(edge);
        ((List<Map<String, Object>>) nodes.get(to).get("prev")).add(Map.of("key", from, "how", how));
        ((List<Map<String, Object>>) nodes.get(from).get("next")).add(Map.of("key", to, "how", how));
    }
}
