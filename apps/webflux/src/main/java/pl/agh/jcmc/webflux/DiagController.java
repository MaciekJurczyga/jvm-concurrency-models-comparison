package pl.agh.jcmc.webflux;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

// Diagnostic only, kept out of /io and /cpu so their responses stay identical across models.
@RestController
class DiagController {

    record ThreadInfo(String thread, boolean virtual) {
    }

    @GetMapping("/diag/thread")
    Mono<ThreadInfo> thread() {
        return Mono.fromSupplier(() -> {
            Thread current = Thread.currentThread();
            return new ThreadInfo(current.toString(), current.isVirtual());
        });
    }
}
