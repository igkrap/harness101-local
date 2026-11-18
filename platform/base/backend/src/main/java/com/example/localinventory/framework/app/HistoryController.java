package com.example.localinventory.framework.app;

import java.util.Map;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Each screen keeps its own history (h_<key>, beside its table r_<key>); a record's history is read through its screen (GET /api/data/{entity}/{id}/history). */
@RestController
public class HistoryController {
    private final RecordStore store;
    public HistoryController(RecordStore store) { this.store = store; }

    /** The history of records the platform made to check a screen (and removed again): taken away with them, so the system's own history
     *  holds only what people and the system did. Administrators (the platform's checking account). */
    @DeleteMapping("/api/system/history")
    public Map<String, Object> forget(@RequestParam String entity, @RequestParam long id) {
        if (!entity.matches("[a-z][a-z0-9_]{1,39}")) return Map.of("removed", 0);
        store.forgetHistory(entity, id);
        return Map.of("removed", 1);
    }
}
