package pl.agh.jcmc.mvc;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

@RestController
class LoadController {

    static final String PASSWORD = "jcmc-benchmark-password";

    record IoResponse(long upstreamDelayMs) {
    }

    record CpuResponse(boolean matches) {
    }

    record UpstreamDelay(long delayMs) {
    }

    private final RestClient upstream;
    private final long ioDelayMs;
    private final BCryptPasswordEncoder encoder;
    private final String passwordHash;

    LoadController(RestClient upstream, AppProperties props) {
        this.upstream = upstream;
        this.ioDelayMs = props.ioDelayMs();
        this.encoder = new BCryptPasswordEncoder(props.bcryptCost());
        // Hash computed once: matches() costs the same as encode() but skips per-request salt
        // generation through a shared SecureRandom, an extra contention point (DECISIONS.md, D8).
        this.passwordHash = encoder.encode(PASSWORD);
    }

    @GetMapping("/io")
    IoResponse io() {
        UpstreamDelay body = upstream.get()
                .uri("/delay?ms={ms}", ioDelayMs)
                .retrieve()
                .body(UpstreamDelay.class);
        return new IoResponse(body.delayMs());
    }

    @GetMapping("/cpu")
    CpuResponse cpu() {
        return new CpuResponse(encoder.matches(PASSWORD, passwordHash));
    }
}
