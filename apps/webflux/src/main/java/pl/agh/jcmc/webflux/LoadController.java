package pl.agh.jcmc.webflux;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

@RestController
class LoadController {

    static final String PASSWORD = "jcmc-benchmark-password";

    record IoResponse(long upstreamDelayMs) {
    }

    record CpuResponse(boolean matches) {
    }

    record UpstreamDelay(long delayMs) {
    }

    private final WebClient upstream;
    private final long ioDelayMs;
    private final BCryptPasswordEncoder encoder;
    private final String passwordHash;

    LoadController(WebClient upstream, AppProperties props) {
        this.upstream = upstream;
        this.ioDelayMs = props.ioDelayMs();
        this.encoder = new BCryptPasswordEncoder(props.bcryptCost());
        // Same as MVC: hash once, matches() per request (DECISIONS.md, D8).
        this.passwordHash = encoder.encode(PASSWORD);
    }

    @GetMapping("/io")
    Mono<IoResponse> io() {
        return upstream.get()
                .uri("/delay?ms={ms}", ioDelayMs)
                .retrieve()
                .bodyToMono(UpstreamDelay.class)
                .map(body -> new IoResponse(body.delayMs()));
    }

    // bcrypt runs on the CPU-sized parallel scheduler, off the event loop; excess work queues there
    // without bound. This choice directly shapes the S2-CPU result (DECISIONS.md, D13).
    @GetMapping("/cpu")
    Mono<CpuResponse> cpu() {
        return Mono.fromCallable(() -> new CpuResponse(encoder.matches(PASSWORD, passwordHash)))
                .subscribeOn(Schedulers.parallel());
    }
}
