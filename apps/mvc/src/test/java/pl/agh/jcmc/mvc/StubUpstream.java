package pl.agh.jcmc.mvc;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

/** Minimal stand-in for apps/fake-api: GET /delay?ms=N, or an immediate 500 when failing. */
final class StubUpstream {

    private final HttpServer server;
    private volatile boolean failing;

    private StubUpstream() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.createContext("/delay", this::handle);
        server.start();
    }

    static StubUpstream start() {
        try {
            return new StubUpstream();
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
    }

    String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    void failing(boolean failing) {
        this.failing = failing;
    }

    private void handle(HttpExchange exchange) throws IOException {
        if (failing) {
            respond(exchange, 500, "{}");
            return;
        }
        long ms = Long.parseLong(exchange.getRequestURI().getQuery().replace("ms=", ""));
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        respond(exchange, 200, "{\"delayMs\":" + ms + "}");
    }

    private static void respond(HttpExchange exchange, int status, String json) throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, body.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(body);
        }
    }
}
