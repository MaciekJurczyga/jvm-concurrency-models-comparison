package pl.agh.jcmc.mvc;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

// Diagnostic only, kept out of /io and /cpu so their responses stay identical across models.
@RestController
class DiagController {

    record ThreadInfo(String thread, boolean virtual) {
    }

    @GetMapping("/diag/thread")
    ThreadInfo thread() {
        Thread current = Thread.currentThread();
        return new ThreadInfo(current.toString(), current.isVirtual());
    }
}
