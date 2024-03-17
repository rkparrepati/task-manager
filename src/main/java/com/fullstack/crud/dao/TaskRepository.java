package com.fullstack.crud.dao;

import org.springframework.data.jpa.repository.JpaRepository;

import com.fullstack.crud.entity.Task;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface TaskRepository extends JpaRepository<Task, Integer> {

    @Query("SELECT t FROM Task t WHERE t.category = :category")
    List<Task> findByCategory(@Param("category") String category);
    @Query("SELECT t FROM Task t WHERE t.category = :category AND t.type = :type")
    List<Task> findAllByCategoryType(@Param("category") String category, @Param("type") String type);

    @Query("SELECT t FROM Task t WHERE t.type = :type")
    List<Task> findByType(@Param("type") String type);
}
