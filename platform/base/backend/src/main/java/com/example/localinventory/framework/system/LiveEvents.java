package com.example.localinventory.framework.system;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * A live channel to every open app window (server-sent events). The server only says what changed
 * ("posts"); the window then reads the new data through the normal API, so permissions still apply.
 */
@RestController
@Component
public class LiveEvents {
    private static final long TIMEOUT_MS = 10 * 60 * 1000L;  // the browser reconnects by itself
    private final List<SseEmitter> listeners = new CopyOnWriteArrayList<>();

    @GetMapping(path = "/api/auth/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter subscribe() {
        SseEmitter emitter = new SseEmitter(TIMEOUT_MS);
        listeners.add(emitter);
        emitter.onCompletion(() -> listeners.remove(emitter));
        emitter.onTimeout(() -> { listeners.remove(emitter); emitter.complete(); });
        emitter.onError(error -> listeners.remove(emitter));
        try { emitter.send(SseEmitter.event().name("ready").data("ok")); } catch (IOException | IllegalStateException gone) { listeners.remove(emitter); }
        return emitter;
    }

    /** Tell every open window that data of this kind changed (e.g. "posts"). Never fails the caller. */
    public void publish(String topic) {
        for (SseEmitter emitter : listeners) {
            try { emitter.send(SseEmitter.event().name(topic).data(String.valueOf(System.currentTimeMillis()))); }
            catch (IOException | IllegalStateException gone) { listeners.remove(emitter); }
        }
    }
}
