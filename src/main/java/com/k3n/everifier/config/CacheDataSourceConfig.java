package com.k3n.everifier.config;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.jdbc.DataSourceBuilder;
import org.springframework.boot.orm.jpa.EntityManagerFactoryBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import javax.sql.DataSource;
import javax.persistence.EntityManagerFactory;
import java.util.HashMap;
import java.util.Map;

@Configuration
@EnableTransactionManagement
@EnableJpaRepositories(
        basePackages = "com.k3n.everifier.repository.cache",
        entityManagerFactoryRef = "cacheEntityManagerFactory",
        transactionManagerRef = "cacheTransactionManager"
)
public class CacheDataSourceConfig {

    @Bean(name = "cacheDataSource")
    @ConfigurationProperties(prefix = "spring.datasource.cache")
    public DataSource cacheDataSource() {
        return DataSourceBuilder.create().build();
    }

    @Bean(name = "cacheEntityManagerFactory")
    public LocalContainerEntityManagerFactoryBean cacheEntityManagerFactory(
            EntityManagerFactoryBuilder builder,
            @Qualifier("cacheDataSource") DataSource dataSource) {

        Map<String, Object> jpaProperties = new HashMap<>();
        jpaProperties.put("hibernate.hbm2ddl.auto", "update");
        jpaProperties.put("hibernate.dialect", "org.hibernate.dialect.MySQL8Dialect");
        jpaProperties.put("hibernate.show_sql", true);

        return builder
                .dataSource(dataSource)
                .packages("com.k3n.everifier.model.cache")
                .persistenceUnit("cache")
                .properties(jpaProperties)
                .build();
    }

    @Bean(name = "cacheTransactionManager")
    public PlatformTransactionManager cacheTransactionManager(
            @Qualifier("cacheEntityManagerFactory") EntityManagerFactory entityManagerFactory) {
        return new JpaTransactionManager(entityManagerFactory);
    }
}