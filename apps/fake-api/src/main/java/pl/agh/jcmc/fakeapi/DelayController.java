package pl.agh.jcmc.fakeapi;

import java.time.Duration;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

@RestController
class DelayController {

    static final long MAX_DELAY_MS = 60_000;

    record DelayResponse(long delayMs) {
    }

    // Mono.delay schedules a timer instead of parking a thread, so the fake API
    // can hold far more concurrent requests than any SUT (DECISIONS.md, D3).
    @GetMapping("/delay")
    Mono<DelayResponse> delay(@RequestParam long ms) {
        if (ms < 0 || ms > MAX_DELAY_MS) {
            return Mono.error(new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "ms must be in [0, " + MAX_DELAY_MS + "]"));
        }
        return Mono.delay(Duration.ofMillis(ms)).thenReturn(new DelayResponse(ms));
    }
}
