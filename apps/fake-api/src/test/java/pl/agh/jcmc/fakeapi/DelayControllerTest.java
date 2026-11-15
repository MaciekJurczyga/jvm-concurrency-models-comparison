package pl.agh.jcmc.fakeapi;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webflux.test.autoconfigure.WebFluxTest;
import org.springframework.test.web.reactive.server.WebTestClient;

@WebFluxTest(DelayController.class)
class DelayControllerTest {

    @Autowired
    WebTestClient client;

    @Test
    void respondsAfterRequestedDelay() {
        long start = System.nanoTime();

        client.get().uri("/delay?ms=200").exchange()
                .expectStatus().isOk()
                .expectBody().json("{\"delayMs\":200}");

        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertThat(elapsedMs).isGreaterThanOrEqualTo(200);
    }

    @Test
    void rejectsOutOfRangeDelay() {
        client.get().uri("/delay?ms=-1").exchange().expectStatus().isBadRequest();
        client.get().uri("/delay?ms=60001").exchange().expectStatus().isBadRequest();
    }

    @Test
    void rejectsMissingParameter() {
        client.get().uri("/delay").exchange().expectStatus().isBadRequest();
    }
}
