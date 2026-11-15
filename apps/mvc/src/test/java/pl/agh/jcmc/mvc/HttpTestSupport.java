package pl.agh.jcmc.mvc;

import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClient;

final class HttpTestSupport {

    private HttpTestSupport() {
    }

    static ResponseEntity<String> get(int port, String path) {
        return RestClient.create("http://localhost:" + port).get().uri(path)
                .retrieve()
                .onStatus(status -> true, (request, response) -> { })
                .toEntity(String.class);
    }
}
