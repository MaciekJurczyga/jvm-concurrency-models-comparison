package pl.agh.jcmc.webflux;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import java.time.Duration;

import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.blockhound.BlockingOperationError;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class NonBlockingTest {

    // Guards the other tests: if BlockHound silently failed to install (e.g. on a newer JDK),
    // their "no blocking" guarantee would be void.
    @Test
    void blockHoundIsActive() {
        Mono<Long> blocking = Mono.delay(Duration.ofMillis(1))
                .doOnNext(tick -> {
                    try {
                        Thread.sleep(1);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                });

        StepVerifier.create(blocking).expectError(BlockingOperationError.class).verify(Duration.ofSeconds(5));
    }

    // BlockHound cannot see CPU-heavy work, so bcrypt staying off the event loop is checked by thread name.
    @Test
    void bcryptRunsOnParallelScheduler() {
        AppProperties props = new AppProperties(URI.create("http://localhost:1"), 100, Duration.ofSeconds(1), 4, 1);
        LoadController controller = new LoadController(WebClient.create(), props);

        StepVerifier.create(controller.cpu().map(response -> Thread.currentThread().getName()))
                .assertNext(thread -> assertThat(thread).startsWith("parallel-"))
                .verifyComplete();
    }

}
