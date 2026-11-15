package pl.agh.jcmc.mvc;

import java.net.http.HttpTimeoutException;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.client.RestClientException;

// 504 vs 502 lets k6 tell dependency timeouts from other dependency failures (DECISIONS.md, D10).
@RestControllerAdvice
class UpstreamErrorHandler {

    record ErrorResponse(String error) {
    }

    @ExceptionHandler(RestClientException.class)
    ResponseEntity<ErrorResponse> upstreamFailure(RestClientException ex) {
        if (isTimeout(ex)) {
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(new ErrorResponse("upstream_timeout"));
        }
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(new ErrorResponse("upstream_error"));
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
