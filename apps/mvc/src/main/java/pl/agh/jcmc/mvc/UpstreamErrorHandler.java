package pl.agh.jcmc.mvc;

import java.net.http.HttpTimeoutException;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.client.RestClientException;

// 504 vs 502 lets k6 tell dependency timeouts from other dependency failures (DECISIONS.md, D10).
@RestControllerAdvice
class UpstreamErrorHandler {

    record ErrorResponse(String error) {
    }

    // Status set on the servlet response instead of returning ResponseEntity: the ResponseEntity path flushes
    // before Tomcat knows the length, so errors went out chunked while WebFlux sends Content-Length (DECISIONS.md, D19).
    @ExceptionHandler(RestClientException.class)
    ErrorResponse upstreamFailure(RestClientException ex, HttpServletResponse response) {
        if (isTimeout(ex)) {
            response.setStatus(HttpStatus.GATEWAY_TIMEOUT.value());
            return new ErrorResponse("upstream_timeout");
        }
        response.setStatus(HttpStatus.BAD_GATEWAY.value());
        return new ErrorResponse("upstream_error");
    }

    private static boolean isTimeout(Throwable ex) {
        for (Throwable t = ex; t != null; t = t.getCause()) {
            if (t instanceof HttpTimeoutException) {
                return true;
            }
        }
        return false;
    }
}
