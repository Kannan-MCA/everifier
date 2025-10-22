package com.k3n.everifier.services;

import com.k3n.everifier.config.BlacklistDomainConfig;
import com.k3n.everifier.config.DisposableDomainConfig;
import com.k3n.everifier.config.WhitelistedDomains;
import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.util.SmtpRcptValidator;
import com.k3n.everifier.util.SmtpRcptValidator.SmtpRecipientStatus;
import com.k3n.everifier.util.SmtpRcptValidator.ValidationResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import javax.naming.Context;
import javax.naming.NamingException;
import javax.naming.directory.*;
import java.io.IOException;
import java.net.IDN;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Service
public class MXLookupService {

    private static final Logger logger = LoggerFactory.getLogger(MXLookupService.class);

    private static final Pattern EMAIL_PATTERN = Pattern.compile(
            "^[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}$", Pattern.CASE_INSENSITIVE);

    private final Set<String> disposableDomains;
    private final Set<String> blacklistDomains;
    private final Set<String> whitelistedDomains;
    private final SmtpRcptValidator smtpRcptValidator;

    @Autowired
    public MXLookupService(DisposableDomainConfig disposableConfig,
                           BlacklistDomainConfig blacklistDomainConfig,
                           WhitelistedDomains whitelistedDomains,
                           SmtpRcptValidator smtpRcptValidator) {
        this.disposableDomains = Optional.ofNullable(disposableConfig.getDomainSet()).orElse(Collections.emptySet());
        this.blacklistDomains = Optional.ofNullable(blacklistDomainConfig.getDomainSet()).orElse(Collections.emptySet());
        this.whitelistedDomains = Optional.ofNullable(whitelistedDomains.getDomainSet()).orElse(Collections.emptySet());
        this.smtpRcptValidator = smtpRcptValidator;
    }

    @Async("taskExecutor")
    public CompletableFuture<EmailValidationResult> categorizeEmailAsync(String email) {
        EmailValidationResult result = categorizeEmail(email);
        return CompletableFuture.completedFuture(result);
    }

    public EmailValidationResult categorizeEmail(final String email) {
        EmailValidationResult result = new EmailValidationResult();
        result.setEmail(email);
        result.setCatchAll(false);
        result.setPortOpened(false);
        result.setConnectionSuccessful(false);
        result.setTranscript(null);
        result.setMailHost(null);
        result.setTimestamp(java.time.LocalDateTime.now().format(
                java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS")));

        if (!isValidEmail(email)) {
            result.setCategory("Invalid");
            return result;
        }

        String domain = extractDomain(email);
        if (domain == null) {
            result.setCategory("Invalid");
            return result;
        }

        if (isWhitelistedDomain(domain)) {
            result.setCategory("Whitelisted");
            return result;
        }
        if (isDisposableDomain(domain)) {
            result.setCategory("Disposable");
            return result;
        }
        if (isBlacklistedDomain(domain)) {
            result.setCategory("Blacklisted");
            return result;
        }

        List<String> mxRecords;
        try {
            mxRecords = getMXRecords(domain);
            if (mxRecords.isEmpty()) {
                result.setCategory("Invalid");
                return result;
            }
        } catch (NamingException e) {
            logger.warn("MX lookup failed for domain {}: {}", domain, e.getMessage());
            result.setCategory("Unknown");
            result.setErrors("MX lookup error: " + e.getMessage());
            return result;
        }

        try {
            if (isCatchAll(mxRecords, domain)) {
                result.setCategory("Catch-All");
                result.setCatchAll(true);
                return result;
            }
        } catch (IOException e) {
            logger.warn("Catch-All detection failed for domain {}: {}", domain, e.getMessage());
            result.setCategory("Unknown");
            result.setErrors("Catch-All detection error: " + e.getMessage());
            return result;
        }

        ValidationResult smtp = smtpCheckStatusWithRetry(mxRecords, email, 2);
        if (smtp == null) {
            result.setCategory("Unknown");
            result.setErrors("SMTP validation returned no result");
            return result;
        }

        String errorMsg = smtp.getErrorMessage() != null ? smtp.getErrorMessage().toLowerCase() : "";
        if (errorMsg.contains("550 5.7.1") || errorMsg.contains("blocked") || errorMsg.contains("spamhaus")) {
            result.setCategory("Blacklisted");
            result.setErrors(smtp.getErrorMessage());
            return result;
        }

        result.setDiagnosticTag(smtp.getDiagnosticTag());
        result.setSmtpCode(smtp.getSmtpCode());
        result.setStatus(smtp.getStatus() != null ? smtp.getStatus().name() : null);
        result.setTranscript(smtp.getFullTranscript());
        result.setMailHost(smtp.getMxHost());
        result.setTimestamp(smtp.getTimestamp());
        result.setPortOpened(true);
        result.setConnectionSuccessful(
                smtp.getStatus() != null && !smtp.getStatus().equals(SmtpRecipientStatus.UnknownFailure)
        );
        if (smtp.getErrorMessage() != null) {
            result.setErrors(smtp.getErrorMessage());
        }

        String tag = smtp.getDiagnosticTag() != null ? smtp.getDiagnosticTag().trim() : "";
        switch (tag) {
            case "Accepted":
                result.setCategory("Valid");
                break;
            case "Forwarded":
                result.setCategory("Forwarded");
                break;
            case "CannotVerify":
                result.setCategory("CannotVerify");
                break;
            case "MailboxBusy":
                result.setCategory("MailboxBusy");
                break;
            case "LocalError":
                result.setCategory("LocalError");
                break;
            case "InsufficientStorage":
                result.setCategory("InsufficientStorage");
                break;
            case "MailboxNotFound":
            case "UserNotLocal":
            case "MailboxNameInvalid":
                result.setCategory("UserNotFound");
                break;
            case "RelayDenied":
                result.setCategory("RelayDenied");
                break;
            case "AccessDenied":
                result.setCategory("AccessDenied");
                break;
            case "Greylisted":
                result.setCategory("Greylisted");
                break;
            case "SyntaxError":
                result.setCategory("SyntaxError");
                break;
            case "TransactionFailed":
                result.setCategory("Invalid");
                break;
            case "BlockedByBlacklist":
                result.setCategory("Blacklisted");
                break;
            default:
                result.setCategory(
                        smtp.getStatus() == SmtpRecipientStatus.TemporaryFailure ? "Unknown" : "Invalid"
                );
        }
        return result;
    }

    private ValidationResult smtpCheckStatusWithRetry(final List<String> mxRecords, final String email, int maxRetries) {
        int attempt = 0;
        ValidationResult result = null;
        String mxHost = extractMxHost(mxRecords.get(0));
        while (attempt < maxRetries) {
            try {
                result = smtpRcptValidator.validateRecipient(mxHost, email);
                if (result != null && result.getStatus() != SmtpRecipientStatus.TemporaryFailure) {
                    return result;
                }
            } catch (Exception e) {
                logger.warn("SMTP validation attempt {} for {} failed: {}", attempt + 1, email, e.getMessage());
            }
            attempt++;
            try {
                Thread.sleep(1000 * attempt);
            } catch (InterruptedException ignored) { }
        }
        return result;
    }

    public boolean isValidEmail(final String email) {
        return email != null && EMAIL_PATTERN.matcher(email).matches();
    }

    public String extractDomain(final String email) {
        if (email == null) return null;
        int atIndex = email.lastIndexOf('@');
        if (atIndex < 0 || atIndex == email.length() - 1) return null;
        String domain = email.substring(atIndex + 1).toLowerCase(Locale.ROOT);
        try {
            domain = IDN.toASCII(domain);
        } catch (Exception ex) {
            // ignore fallback
        }
        return domain;
    }

    public boolean isDisposableDomain(final String domain) {
        return disposableDomains.contains(domain);
    }

    public boolean isBlacklistedDomain(final String domain) {
        return blacklistDomains.contains(domain);
    }

    public boolean isWhitelistedDomain(final String domain) {
        return whitelistedDomains.contains(domain);
    }

    public List<String> getMXRecords(final String domain) throws NamingException {
        final Hashtable<String, String> env = new Hashtable<>();
        env.put(Context.INITIAL_CONTEXT_FACTORY, "com.sun.jndi.dns.DnsContextFactory");
        final DirContext ctx = new InitialDirContext(env);

        final Attributes attrs = ctx.getAttributes(domain, new String[]{"MX"});
        final Attribute attr = attrs.get("MX");

        if (attr == null || attr.size() == 0) {
            final Attributes aAttrs = ctx.getAttributes(domain, new String[]{"A"});
            final Attribute aAttr = aAttrs.get("A");

            if (aAttr == null || aAttr.size() == 0) return Collections.emptyList();

            return IntStream.range(0, aAttr.size())
                    .mapToObj(i -> {
                        try {
                            return "0 " + aAttr.get(i).toString();
                        } catch (NamingException e) {
                            throw new RuntimeException(e);
                        }
                    })
                    .collect(Collectors.toList());
        }

        return IntStream.range(0, attr.size())
                .mapToObj(i -> {
                    try {
                        return attr.get(i).toString();
                    } catch (NamingException e) {
                        return "";
                    }
                })
                .filter(s -> !s.isEmpty())
                .sorted(Comparator.comparingInt(this::parsePriority))
                .collect(Collectors.toList());
    }

    private int parsePriority(final String mxRecord) {
        final String[] parts = mxRecord.split("\\s+");
        try {
            return Integer.parseInt(parts[0]);
        } catch (NumberFormatException | ArrayIndexOutOfBoundsException e) {
            return Integer.MAX_VALUE;
        }
    }

    public boolean isCatchAll(final List<String> mxRecords, final String domain) throws IOException {
        if (mxRecords == null || mxRecords.isEmpty()) return false;
        final String mxHost = extractMxHost(mxRecords.get(0));
        return smtpRcptValidator.checkSmtpCatchAllSingleSession(mxHost, "nonexistent@" + domain, domain);
    }

    private String extractMxHost(final String mxRecord) {
        final String[] parts = mxRecord.split("\\s+");
        String host = parts.length >= 2 ? parts[1] : mxRecord;
        return host.endsWith(".") ? host.substring(0, host.length() - 1) : host;
    }
}