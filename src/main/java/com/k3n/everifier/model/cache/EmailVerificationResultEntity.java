package com.k3n.everifier.model.cache;

import javax.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "email_verification_results")
public class EmailVerificationResultEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String email;

    @Lob
    private String verificationResultJson;  // Storing JSON result as string

    @Column(nullable = false)
    private LocalDateTime cachedAt;  // Timestamp to manage cache TTL

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getVerificationResultJson() { return verificationResultJson; }
    public void setVerificationResultJson(String verificationResultJson) { this.verificationResultJson = verificationResultJson; }
    public LocalDateTime getCachedAt() { return cachedAt; }
    public void setCachedAt(LocalDateTime cachedAt) { this.cachedAt = cachedAt; }
}
