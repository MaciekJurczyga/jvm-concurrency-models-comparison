package pl.agh.jcmc.mvc;

import static org.assertj.core.api.Assertions.assertThat;
import static pl.agh.jcmc.mvc.HttpTestSupport.get;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"app.io-delay-ms=50", "app.bcrypt-cost=4"})
@ActiveProfiles("virtual")
class VirtualProfileTest {

    static final StubUpstream UPSTREAM = StubUpstream.start();

    @DynamicPropertySource
    static void upstream(DynamicPropertyRegistry registry) {
        registry.add("app.upstream-url", UPSTREAM::url);
    }

    @LocalServerPort
    int port;

    @Test
    void requestsRunOnVirtualThreads() {
        assertThat(get(port, "/diag/thread").getBody()).contains("\"virtual\":true");
    }

    @Test
    void endpointsReturnSameResponsesAsPlatformProfile() {
        assertThat(get(port, "/io").getBody()).isEqualTo("{\"upstreamDelayMs\":50}");
        assertThat(get(port, "/cpu").getBody()).isEqualTo("{\"matches\":true}");
    }

    @Test
    void prometheusCarriesModelTag() {
        assertThat(get(port, "/actuator/prometheus").getBody()).contains("model=\"virtual\"");
    }
}
