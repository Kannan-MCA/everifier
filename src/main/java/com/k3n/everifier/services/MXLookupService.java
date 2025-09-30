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

        // Step 1: Syntax validation
        if (!isValidEmail(email)) {
            result.setCategory("Invalid");
            return result;
        }

        // Extract domain
        String domain = extractDomain(email);
        if (domain == null) {
            result.setCategory("Invalid");
            return result;
        }

        // Step 2: Domain whitelist/blacklist/disposable checks
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

        // Step 3: DNS MX record lookup
        List<String> mxRecords;
        try {
            mxRecords = getMXRecords(domain);
            if (mxRecords.isEmpty()) {
                result.setCategory("Invalid");
                return result;
            }
        } catch (NamingException e) {
            result.setCategory("Unknown");
            result.setErrors(e.getMessage());
            return result;
        }

        // Step 4: Catch-All detection
        try {
            if (isCatchAll(mxRecords, domain)) {
                result.setCategory("Catch-All");
                result.setCatchAll(true);
                return result;
            }
        } catch (IOException e) {
            result.setCategory("Unknown");
            result.setErrors(e.getMessage());
            return result;
        }

        // Step 5: SMTP Recipient Validation + TLS support (existing logic)
        ValidationResult smtp;
        try {
            smtp = smtpCheckStatus(mxRecords, email);
        } catch (Exception ex) {
            logger.warn("SMTP validation failed for email {}: {}", email, ex.getMessage(), ex);
            // Fallback: mark as unknown with error
            result.setCategory("Unknown");
            result.setErrors("SMTP validation failed: " + ex.getMessage());
            return result;
        }
        if (smtp == null) {
            result.setCategory("Unknown");
            return result;
        }

        // Step 6: Handle blacklist SMTP errors explicitly
        String errorMsg = smtp.getErrorMessage() != null ? smtp.getErrorMessage().toLowerCase() : "";
        if (errorMsg.contains("550 5.7.1") || errorMsg.contains("blocked") || errorMsg.contains("spamhaus")) {
            result.setCategory("Blacklisted");
            result.setErrors(smtp.getErrorMessage());
            return result;
        }

        // Set detailed SMTP result fields
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

        // Step 7: Categorize based on SMTP diagnosticTag
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


    public boolean isValidEmail(final String email) {
        return email != null && EMAIL_PATTERN.matcher(email).matches();
    }

    public String extractDomain(final String email) {
        if (email == null) return null;
        final int atIndex = email.lastIndexOf('@');
        if (atIndex < 0 || atIndex == email.length() - 1) return null;
        String domain = email.substring(atIndex + 1).toLowerCase(Locale.ROOT);

        try {
            domain = IDN.toASCII(domain);
        } catch (Exception ignore) {}

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

        List<String> mxRecords = IntStream.range(0, attr.size())
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

        return mxRecords;
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

    private ValidationResult smtpCheckStatus(final List<String> mxRecords, final String email) {
        if (mxRecords == null || mxRecords.isEmpty()) return null;
        String mxHost = extractMxHost(mxRecords.get(0));
        return smtpRcptValidator.validateRecipient(mxHost, email);
    }

    private String extractMxHost(final String mxRecord) {
        final String[] parts = mxRecord.split("\\s+");
        String host = parts.length >= 2 ? parts[1] : mxRecord;
        return host.endsWith(".") ? host.substring(0, host.length() - 1) : host;
    }
}
